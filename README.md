# Torob Reverse Proxy

این پروژه یک reverse proxy کوچک با Docker و Nginx است. برنامه اصلی شما به این سرویس درخواست می‌زند، این سرویس همان درخواست را به ترب می‌فرستد و پاسخ ترب را برمی‌گرداند.

## تصویر ساده مسیر درخواست

```text
your main project -> this proxy -> Torob
your main project <- this proxy <- Torob
```

## فایل‌ها

- `Dockerfile`: ایمیج Nginx را می‌سازد و کانفیگ proxy را داخل آن می‌گذارد.
- `compose.yaml`: اجرای محلی با Docker Compose.
- `nginx/templates/default.conf.template`: کانفیگ اصلی Nginx. متغیرهای محیطی قبل از اجرای Nginx جایگزین می‌شوند.

## اجرای محلی

اول Docker Desktop را باز کنید، بعد در همین پوشه اجرا کنید:

```powershell
docker compose up --build
```

تست سلامت:

```powershell
curl http://localhost:8080/health
```

برای زدن درخواست به ترب از مسیر proxy:

```powershell
curl "http://localhost:8080/v4/base-product/search/?query=گوشی" -H "X-Proxy-Token: change-this-token"
```

endpoint ترب که این پروژه برای آن آماده شده:

```text
https://api.torob.com/v4/base-product/search/
```

از داخل پروژه اصلی خودتان باید همین مسیر را روی دامنه proxy بزنید:

```text
http://localhost:8080/v4/base-product/search/?query=گوشی
```

## تنظیمات مهم

این متغیرها را در محیط دیپلوی تنظیم کنید:

```text
TOROB_UPSTREAM_SCHEME=https
TOROB_UPSTREAM_HOST=api.torob.com
PROXY_TOKEN=یک-رمز-طولانی-و-تصادفی
CORS_ALLOW_ORIGIN=*
PORT=8080
```

اگر API واقعی ترب روی دامنه دیگری است، فقط `TOROB_UPSTREAM_HOST` را عوض کنید.

## اتصال از پروژه اصلی

در پروژه اصلی به جای اینکه مستقیم به ترب بزنید:

```text
https://api.torob.com/v4/base-product/search/?query=گوشی
```

به دامنه proxy بزنید:

```text
https://your-proxy-domain.com/v4/base-product/search/?query=گوشی
```

و هدر زیر را هم بفرستید:

```text
X-Proxy-Token: همان مقداری که برای PROXY_TOKEN گذاشته‌اید
```

مثال Python:

```python
import requests

PROXY_BASE_URL = "https://your-proxy-domain.com"
PROXY_TOKEN = "همان مقدار PROXY_TOKEN"

response = requests.get(
    f"{PROXY_BASE_URL}/v4/base-product/search/",
    params={"query": "گوشی"},
    headers={"X-Proxy-Token": PROXY_TOKEN},
    timeout=30,
)
response.raise_for_status()
data = response.json()
```

اگر سه proxy روی همروش ساختید، می‌توانید در پروژه Python اصلی چند URL بدهید و اگر اولی خطا داد دومی امتحان شود. نمونه آماده در فایل `examples/python_failover_client.py` است.

نمونه env برای سه مسیر:

```text
TOROB_PROXY_URLS=https://proxy-1.example.com,https://proxy-2.example.com,https://proxy-3.example.com
TOROB_PROXY_TOKEN=همان مقدار PROXY_TOKEN
```

اگر پروژه اصلی باید فقط به یک آدرس درخواست بزند و خود proxy سه مسیر پشتیبان را مدیریت کند، فایل [HAMRAVESH_GATEWAY_DEPLOY.md](HAMRAVESH_GATEWAY_DEPLOY.md) را ببینید. در آن مدل یک اپ gateway جلوی سه اپ worker قرار می‌گیرد.

## دیپلوی روی همروش یا سرویس مشابه

برای دیپلوی، معمولا فقط یک پروژه Docker لازم است، نه سه پروژه. سه پروژه زمانی معنی دارد که مثلا برنامه اصلی، proxy، و یک دیتابیس/سرویس جدا هر کدام جداگانه دیپلوی شوند. برای این proxy ساده، همین یک پروژه کافی است.

راهنمای قدم به قدم همروش در فایل [HAMRAVESH_DEPLOY.md](HAMRAVESH_DEPLOY.md) آمده است.

مراحل کلی:

1. این پوشه را داخل یک repository مثل GitHub/GitLab بگذارید.
2. در پنل همروش یک پروژه/سرویس Docker بسازید.
3. repository را وصل کنید.
4. متغیرهای محیطی بالا را در پنل تنظیم کنید.
5. پورت سرویس را `80` بگذارید، چون Nginx داخل کانتینر روی پورت 80 گوش می‌دهد.
6. دامنه یا زیردامنه‌ای که همروش می‌دهد را بردارید و در پروژه اصلی استفاده کنید.

## نکته امنیتی

این proxy نباید بدون token عمومی شود. اگر `PROXY_TOKEN` ساده یا پیش‌فرض بماند، هر کسی که دامنه proxy را داشته باشد می‌تواند از آن استفاده کند.

## سوال‌هایی که باید از دوستتان یا تیم ترب بپرسید

1. آدرس دقیق API ترب چیست؟ مثلا `api.torob.com` یا دامنه دیگری؟
2. مسیرهایی که باید proxy شوند کدام‌اند؟
3. آیا ترب نیاز به هدر خاص، API key، User-Agent یا IP allowlist دارد؟
4. همروش برای پروژه Docker شما پورت داخلی را چند می‌خواهد؟ اگر خودش پورت 80 را expose می‌کند، تنظیم فعلی درست است.
