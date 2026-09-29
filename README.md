# Churn Radar

Demostración educativa que lleva un modelo de churn desde un flujo local a un
proceso versionado, probado, revisado, desplegado con aprobación y monitoreado.
Todos los registros, nombres de entidades e identificadores de este repositorio
son sintéticos.

## Flujo demostrado

```text
Issue -> rama -> commits -> Pull Request -> CI -> revisión requerida
      -> merge -> aprobación de production -> revisión candidata al 10%
      -> observación -> promoción al 100% o rollback
```

El repositorio conserva el nombre `credito`, pero usa `churn-radar` como nombre
funcional de la aplicación y de los recursos.

## Arquitectura

```text
GitHub Actions
  |-- CI: datos + pytest + AUC >= 0.78 + docker build
  `-- CD: OIDC + Bicep what-if + ACR build + aprobación
                    |
                    v
Azure Container Registry ---> Azure Container Apps
                                  |-- revisión estable: 90%
                                  `-- revisión candidata: 10%
                                            |
                                            v
                         Log Analytics + Application Insights
```

La imagen contiene un artefacto entrenado de forma determinista. La etiqueta de
la imagen, la revisión y `model_version` usan el SHA del commit para mantener
trazabilidad.

## Estructura

```text
.github/
  workflows/ci-model.yml
  workflows/cd-infra.yml
  CODEOWNERS
  dependabot.yml
  pull_request_template.md
data/sample_clientes_nomina.csv
infra/main.bicep
src/features.py
src/train.py
src/score.py
tests/test_features.py
tests/test_data_quality.py
Dockerfile
requirements.txt
```

## Requisitos locales

- Python 3.11
- Docker, para validar la imagen
- Azure CLI y extensión `containerapp`, para desplegar
- Una suscripción de Azure con permisos para crear recursos y asignaciones de rol

En PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Datos sintéticos

`data/sample_clientes_nomina.csv` contiene 600 clientes ficticios de:

- `Banco Demo A`
- `Banco Demo B`
- `Banco Demo C`

El contrato incluye seis medidas mensuales de mora, ingreso, saldo, antigüedad,
número de productos y el objetivo binario `churn`. La semilla usada para crear
el archivo es fija, por lo que la prueba de AUC no fluctúa entre ejecuciones.

Para demostrar una falla de calidad, trabaje en una rama descartable, introduzca
un valor vacío en una columna requerida y ejecute:

```powershell
python -m pytest tests/test_data_quality.py -q
```

Restaure el dato antes de integrar el cambio. No use información real para esta
actividad.

## Entrenamiento y pruebas

```powershell
python -m pytest tests/test_data_quality.py -q
python -m pytest tests/ -q
python src/train.py --check-auc 0.78
```

El último comando guarda `artifacts/model.joblib` y devuelve un código distinto
de cero si el ROC AUC es inferior a `0.78`.

Opciones útiles:

```powershell
python src/train.py `
  --data data/sample_clientes_nomina.csv `
  --output artifacts/model.joblib `
  --model-version local-v1 `
  --check-auc 0.78
```

## API de scoring

Después de entrenar:

```powershell
$env:MODEL_PATH = "artifacts/model.joblib"
uvicorn src.score:app --host 0.0.0.0 --port 8000
```

Verifique salud:

```powershell
Invoke-RestMethod http://localhost:8000/health
```

Solicite un score:

```powershell
$body = @{
  entidad = "Banco Demo C"
  mora_1m = 18
  mora_2m = 19
  mora_3m = 20
  mora_4m = 18
  mora_5m = 20
  mora_6m = 19
  ingreso_mensual = 1600000
  saldo_credito = 30000000
  antiguedad_meses = 6
  num_productos = 1
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri http://localhost:8000/score `
  -ContentType "application/json" `
  -Body $body
```

Respuesta esperada:

```json
{
  "churn_probability": 0.98,
  "churn_prediction": 1,
  "model_version": "local-v1",
  "drift_alert": false
}
```

Las métricas Prometheus están disponibles en:

```text
GET /metrics
```

## Contenedor

```powershell
docker build --build-arg MODEL_VERSION=local-container -t churn-radar:local .
docker run --rm -p 8000:8000 churn-radar:local
```

La imagen ejecuta la API con un usuario sin privilegios y entrena el artefacto
durante la construcción.

## CI

`.github/workflows/ci-model.yml` se ejecuta en cada Pull Request:

1. Instala Python 3.11 y las dependencias.
2. Ejecuta toda la suite `pytest`, incluida la calidad de datos.
3. Exige AUC mínimo de `0.78`.
4. Construye la imagen.

Configure `validar-modelo` como status check requerido para `main`.

## Azure

### Despliegue manual de infraestructura

```powershell
az login

az group create `
  --name rg-churn-radar-demo `
  --location eastus

az bicep build --file infra/main.bicep

az deployment group what-if `
  --resource-group rg-churn-radar-demo `
  --template-file infra/main.bicep `
  --parameters location=eastus deployContainerApp=false

az deployment group create `
  --name churn-radar-base `
  --resource-group rg-churn-radar-demo `
  --template-file infra/main.bicep `
  --parameters location=eastus deployContainerApp=false
```

El workflow de CD completa la construcción en ACR y la creación o actualización
de Container Apps. `main.bicep` aprovisiona:

- Azure Container Registry
- Identidad administrada con `AcrPull`
- Log Analytics
- Application Insights
- Container Apps Environment
- Container App con ingress HTTPS, sondas y múltiples revisiones

### Autenticación OIDC de GitHub Actions

Configure una identidad federada para este repositorio y cree estas variables en
el GitHub Environment `production`:

- `AZURE_CLIENT_ID`
- `AZURE_TENANT_ID`
- `AZURE_SUBSCRIPTION_ID`

No almacene un client secret. El principal necesita permisos para desplegar
recursos y crear la asignación `AcrPull` en el resource group de la demo.

### Rollout y rollback

Ejecute `CD - Churn Radar` con:

- `deploy-canary`: publica una imagen con el SHA y, si ya existe una versión
  estable, reparte tráfico `90%` estable y `10%` candidata.
- `promote`: requiere `target_revision` y asigna `100%` a la candidata.
- `rollback`: requiere la revisión estable en `target_revision` y le devuelve
  `100%` del tráfico.

Revise las revisiones disponibles antes de promover:

```powershell
az containerapp revision list `
  --name churn-radar-api `
  --resource-group rg-churn-radar-demo `
  --query "[].{name:name,active:properties.active,traffic:properties.trafficWeight}" `
  --output table
```

El job usa el Environment `production`; configure revisores obligatorios para
que GitHub registre la aprobación antes de modificar Azure.

### Limpieza

```powershell
az group delete `
  --name rg-churn-radar-demo `
  --yes `
  --no-wait
```

## Monitoreo

La API registra por solicitud:

- latencia y estado;
- versión del modelo;
- entidad sintética;
- probabilidad de churn;
- señal de drift.

Además, `/metrics` expone contadores e histogramas para solicitudes, errores,
latencia y distribución de scores.

Consultas orientativas en Application Insights:

```kusto
AppRequests
| summarize
    disponibilidad = 100.0 * countif(Success == true) / count(),
    p995_ms = percentile(DurationMs, 99.5),
    errores = countif(Success == false)
  by bin(TimeGenerated, 1h)
```

```kusto
AppTraces
| where Message has '"event": "scoring"'
| extend evento = parse_json(Message)
| summarize
    score_promedio = avg(todouble(evento.score)),
    alertas_drift = countif(tobool(evento.drift_alert))
  by tostring(evento.entity), tostring(evento.model_version), bin(TimeGenerated, 1h)
```

SLO de la demostración:

> 99.5% de las solicitudes de scoring responden en menos de 400 ms, medido
> mensualmente.

El `0.5%` restante es el error budget. Si se consume, se prioriza estabilización
sobre nuevos despliegues. La señal de drift incluida es deliberadamente simple:
compara la media móvil de scores por entidad con la línea base del entrenamiento.
No sustituye un sistema de monitoreo estadístico de producción.

## Configuración manual de GitHub

### Project e issues

1. Cree el Project `Churn Radar - Sprint 1`.
2. Configure las vistas o estados `Backlog`, `En progreso`,
   `En revisión de Riesgo` y `Listo`.
3. Cree issues #1 a #5 para feature de mora, calidad de datos, modelo,
   infraestructura y monitoreo.
4. Cree labels `datos`, `modelo` y `riesgo`.
5. Cree el milestone `Cierre trimestral`.
6. Asigne issue #1 al instructor, agréguelo al milestone y úselo para la rama
   `feature/variable-mora-6m`.

Ejemplo:

```powershell
git checkout -b feature/variable-mora-6m
git add src/features.py tests/test_features.py
git commit -m "feat: agregar promedio de mora 6m (closes #1)"
git push -u origin feature/variable-mora-6m
```

### Protección de `main`

Configure:

- Pull Request obligatorio.
- Al menos una aprobación.
- aprobación de CODEOWNERS.
- check requerido `validar-modelo`.
- conversaciones resueltas antes del merge.
- bloqueo de force push y eliminación de rama.

Actualice `.github/CODEOWNERS` con equipos reales si el repositorio pertenece a
una organización. Los equipos deben existir y tener acceso al repositorio.

### Seguridad

- Active secret scanning y push protection.
- Confirme que Dependabot alerts y security updates estén activos.
- Para mostrar secret scanning, use exclusivamente un patrón de prueba
  oficialmente documentado por el proveedor, en una rama descartable.
- No use secretos reales, plausibles o reutilizables.
- Elimine la rama y cualquier valor de prueba al terminar la actividad.

## Lista de preparación para la clase

- Existe una ejecución verde de CI.
- El Environment `production` tiene revisores.
- La identidad OIDC funciona.
- Hay una revisión estable lista para comparar con la candidata.
- Están preparadas consultas de monitoreo y tráfico de prueba.
- Existe una rama de respaldo con el cambio completado.
- Hay capturas o grabaciones breves fuera del repositorio para contingencias de
  red, permisos o disponibilidad de Azure.
