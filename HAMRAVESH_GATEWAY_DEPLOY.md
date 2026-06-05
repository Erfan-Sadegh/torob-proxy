# راهنمای معماری یک ورودی و سه proxy پشتیبان

اگر پروژه Python اصلی فقط باید به یک آدرس درخواست بزند، باید یک اپ جلویی یا gateway داشته باشید.

مسیر درخواست:

```text
Python main project
  -> torob-proxy-gateway
  -> torob-proxy-1 / torob-proxy-2 / torob-proxy-3
  -> api.torob.com
```

در این معماری در همروش 4 اپ دارید:

```text
torob-proxy-gateway
torob-proxy-1
torob-proxy-2
torob-proxy-3
```

## اپ‌های worker

این سه اپ مستقیم به ترب وصل می‌شوند.

برای هر سه worker:

```text
Dockerfile path:
Dockerfile
```

```text
Container port:
80
```

```text
Readiness Probe:
/health
```

متغیرهای محیطی:

```text
TOROB_UPSTREAM_SCHEME=https
TOROB_UPSTREAM_HOST=api.torob.com
PROXY_TOKEN=یک-رمز-مشترک-برای-workerها
CORS_ALLOW_ORIGIN=*
```

## اپ gateway

این اپ را پروژه Python اصلی صدا می‌زند و خودش بین سه worker failover می‌کند.

برای gateway:

```text
Dockerfile path:
Dockerfile.gateway
```

```text
Container port:
80
```

```text
Readiness Probe:
/health
```

متغیرهای محیطی gateway:

```text
WORKER_1_HOST=دامنه-worker-1-بدون-https
WORKER_2_HOST=دامنه-worker-2-بدون-https
WORKER_3_HOST=دامنه-worker-3-بدون-https
WORKER_PROXY_TOKEN=همان-PROXY_TOKEN-workerها
GATEWAY_PROXY_TOKEN=رمزی-که-پروژه-اصلی-میفرستد
CORS_ALLOW_ORIGIN=*
```

مثال:

```text
WORKER_1_HOST=torob-proxy-1.erfanclash20178-calm-moon.svc
WORKER_2_HOST=torob-proxy-2.erfanclash20178-calm-moon.svc
WORKER_3_HOST=torob-proxy-3.erfanclash20178-calm-moon.svc
WORKER_PROXY_TOKEN=worker-secret-123
GATEWAY_PROXY_TOKEN=gateway-secret-456
CORS_ALLOW_ORIGIN=*
```

برای مقدارهای `WORKER_*_HOST` بهتر است از «آدرس داخلی» همروش استفاده کنید، نه دامنه عمومی. در عکس پنل، آدرس داخلی شبیه این است:

```text
torob-proxy.erfanclash20178-calm-moon.svc
```

برای سه worker هم احتمالا همین الگو را دارید، فقط نام اپ فرق می‌کند.

## پروژه Python اصلی

پروژه اصلی فقط gateway را صدا می‌زند:

```python
import requests

response = requests.get(
    "https://GATEWAY_DOMAIN/v4/base-product/search/",
    params={"query": "گوشی"},
    headers={"X-Proxy-Token": "GATEWAY_PROXY_TOKEN"},
    timeout=30,
)
response.raise_for_status()
data = response.json()
```

پروژه اصلی لازم نیست آدرس سه worker را بداند.
