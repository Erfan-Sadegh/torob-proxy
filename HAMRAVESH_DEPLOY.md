# راهنمای دیپلوی روی همروش

این راهنما برای وقتی است که می‌خواهید همین proxy را روی همروش بالا بیاورید و پروژه Python اصلی‌تان به جای ترب، به این proxy درخواست بزند.

## 1. آماده کردن repository

اگر GitHub یا GitLab دارید:

1. یک repository جدید بسازید، مثلا با نام `torob-reverse-proxy`.
2. فایل‌های همین پوشه را داخل آن push کنید.
3. فایل `.env` را push نکنید. `.gitignore` جلوی این کار را گرفته است.

اگر Git بلد نیستید، از دوستتان بخواهید همین پوشه را روی GitHub/GitLab بگذارد.

## 2. ساخت پروژه در همروش

در پنل همروش:

1. یک پروژه/سرویس جدید بسازید.
2. نوع پروژه را Dockerfile یا ساخت از repository انتخاب کنید، نه ایمیج خام `nginx`.
3. repository مرحله قبل را وصل کنید.
4. مسیر Dockerfile را همین مقدار بگذارید:

```text
Dockerfile
```

5. اگر پنل پورت داخلی یا container port خواست، مقدار زیر را بدهید:

```text
80
```

Nginx داخل کانتینر روی پورت 80 گوش می‌دهد. پورت بیرونی را خود همروش با دامنه عمومی مدیریت می‌کند.

اگر در پنل فقط حالت Docker Image دارید، نباید image را `nginx` بگذارید؛ آن فقط Nginx خام است و کانفیگ proxy ما را ندارد. در آن حالت باید اول image همین repository ساخته و روی Docker Hub/GHCR منتشر شود، بعد همان image اختصاصی را در همروش بدهید.

## 3. تنظیم Environment Variables

در بخش Environment Variables یا Config Vars این‌ها را بگذارید:

```text
TOROB_UPSTREAM_SCHEME=https
TOROB_UPSTREAM_HOST=api.torob.com
PROXY_TOKEN=یک-رمز-طولانی-تصادفی
CORS_ALLOW_ORIGIN=*
```

برای ساخت token در PowerShell خودتان می‌توانید بزنید:

```powershell
-join ((48..57) + (65..90) + (97..122) | Get-Random -Count 48 | ForEach-Object {[char]$_})
```

خروجی را برای `PROXY_TOKEN` بگذارید.

اگر پروژه اصلی‌تان frontend ندارد و فقط Python backend است، مقدار `CORS_ALLOW_ORIGIN=*` فعلا مشکلی ایجاد نمی‌کند. اگر frontend مستقیم از مرورگر به proxy می‌زند، بهتر است بعدا مقدارش را دامنه همان frontend بگذارید.

## 4. Deploy

بعد از تنظیمات:

1. Deploy یا Build را بزنید.
2. منتظر بمانید build تمام شود.
3. دامنه‌ای که همروش به سرویس می‌دهد را بردارید. مثلا:

```text
https://torob-proxy.example.hamravesh.net
```

## 5. تست بعد از deploy

اول health را تست کنید:

```powershell
curl https://YOUR_PROXY_DOMAIN/health
```

باید جواب بگیرید:

```text
ok
```

بعد endpoint ترب را از مسیر proxy تست کنید:

```powershell
curl "https://YOUR_PROXY_DOMAIN/v4/base-product/search/?query=test" -H "X-Proxy-Token: YOUR_PROXY_TOKEN"
```

اگر این درخواست در همروش جواب داد، یعنی مشکل دسترسی شبکه حل شده است.

اگر `504` گرفتید، یعنی همروش هم از شبکه خودش به `api.torob.com` وصل نمی‌شود یا ترب ارتباط را بسته است.

اگر `401` گرفتید، یعنی `X-Proxy-Token` را نفرستاده‌اید یا مقدارش با `PROXY_TOKEN` یکی نیست.

اگر `404` گرفتید، یعنی مسیر اشتباه است. فقط این مسیر باز است:

```text
/v4/base-product/search/
```

## 6. تغییر در پروژه Python اصلی

در پروژه اصلی، هر جا این آدرس را می‌زنید:

```text
https://api.torob.com/v4/base-product/search/
```

آن را به دامنه proxy تغییر بدهید:

```text
https://YOUR_PROXY_DOMAIN/v4/base-product/search/
```

و هدر token را اضافه کنید:

```python
headers={"X-Proxy-Token": "YOUR_PROXY_TOKEN"}
```

نمونه کامل:

```python
import requests

response = requests.get(
    "https://YOUR_PROXY_DOMAIN/v4/base-product/search/",
    params={"query": "گوشی"},
    headers={"X-Proxy-Token": "YOUR_PROXY_TOKEN"},
    timeout=30,
)
response.raise_for_status()
data = response.json()
```

## 7. اگر سه proxy می‌خواهید

برای failover می‌توانید سه اپ جدا در همروش بسازید. هر سه اپ می‌توانند از همین repository و همین Dockerfile ساخته شوند.

برای هر سه اپ:

```text
Dockerfile path: Dockerfile
Container port: 80
Readiness Probe: /health
```

متغیرهای محیطی هم برای هر سه یکی است:

```text
TOROB_UPSTREAM_SCHEME=https
TOROB_UPSTREAM_HOST=api.torob.com
PROXY_TOKEN=یک-رمز-طولانی-تصادفی
CORS_ALLOW_ORIGIN=*
```

می‌توانید برای هر سه یک `PROXY_TOKEN` یکسان بگذارید تا پروژه Python اصلی ساده‌تر شود. بعد در پروژه اصلی سه دامنه همروش را با کاما ذخیره کنید:

```text
TOROB_PROXY_URLS=https://proxy-1.example.com,https://proxy-2.example.com,https://proxy-3.example.com
TOROB_PROXY_TOKEN=همان مقدار PROXY_TOKEN
```

نمونه کد آماده در `examples/python_failover_client.py` است.

## 8. چیزهایی که اگر به مشکل خوردید باید بفرستید

اگر deploy یا تست جواب نداد، این‌ها را بفرستید:

1. اسکرین‌شات تنظیمات پورت و environment variables در همروش.
2. لاگ build همروش.
3. لاگ runtime همروش بعد از زدن request.
4. دامنه proxy که همروش داده است.

token واقعی را در پیام عمومی نفرستید. اگر لازم شد فقط چند کاراکتر اول و آخرش را بفرستید.
