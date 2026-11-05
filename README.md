# ویتالز

داشبورد کوچک و رمزدار برای دیدن **بسته‌های جاری AvalAI** و **اعتبار باقی‌مانده** در دو حساب:

- کلید شخصی (`AVALAI_PERSONAL_API_KEY`)
- کلید شرکت (`AVALAI_COMPANY_API_KEY`)

هر بخش مستقل خوانده می‌شود؛ اگر یکی از کلیدها تنظیم نشده باشد یا AvalAI پاسخ ندهد، بخش دیگر سالم می‌ماند.

## چه چیزی نشان داده می‌شود

برای هر حساب:

- جمع اعتبار قابل استفاده: بسته‌های فعال + اعتبار اصلی
- تفکیک «بسته‌ها» و «اعتبار اصلی»
- هر بسته با مبلغ باقی‌مانده، درصد مصرف، تاریخ انقضای شمسی و زمان باقی‌مانده
- وضعیت: بسته‌ی روزانه/هفتگی فعال، مصرف از اعتبار اصلی، تمام‌شده، یا نامشخص
- هشدار برای بسته‌های منقضی‌شده‌ای که هنوز موجودی دارند

اعداد از پاسخ `GET https://api.avalai.ir/user/v1/credit` خوانده می‌شوند. مقدارها به تومان‌اند و فقط سمت سرور پردازش می‌شوند؛ کلیدها هیچ‌وقت به مرورگر نمی‌رسند.

## امنیت

- TLS و گواهی خودکار با Caddy؛ برنامه فقط روی `127.0.0.1:8010` گوش می‌دهد.
- رمز عبور با **Argon2id** هش می‌شود؛ متن رمز در هیچ فایلی ذخیره نمی‌شود.
- نشست با کوکی امضاشده (`__Host-vitals`) و پرچم‌های `HttpOnly`، `Secure` و `SameSite=Lax`.
- توکن CSRF برای ورود و خروج؛ نشست در زمان ورود کامل بازنشانی می‌شود.
- محدودیت تلاش ورود: ۵ تلاش ناموفق در ۱۰ دقیقه ← ۱۵ دقیقه قفل برای همان IP.
- هدرهای امنیتی: CSP بدون inline، `frame-ancestors 'none'`، `nosniff`، HSTS، `Referrer-Policy` و `Permissions-Policy`.
- `TrustedHost` برای رد Hostهای ناشناخته؛ بدنه‌ی فرم‌ها محدود به ۴ کیلوبایت است.
- سرویس systemd با `ProtectSystem=strict`، `ProtectHome=read-only`، `NoNewPrivileges` و `PrivateTmp` اجرا می‌شود.
- فونت وزیرمتن و همه‌ی دارایی‌ها self-host هستند؛ هیچ درخواستی به CDN یا سرویس خارجی زده نمی‌شود.
- خطاهای AvalAI به‌صورت پیام کوتاه و بدون افشای کلید یا بدنه‌ی پاسخ نمایش داده می‌شوند.
- داده‌ها ۶۰ ثانیه کش می‌شوند تا هر بار باز شدن صفحه به AvalAI فشار نیاورد؛ خطا هم ۱۲۰ ثانیه به خاطر سپرده می‌شود.

## راه‌اندازی

پیش‌نیاز: Python 3.12 یا جدیدتر و [uv](https://docs.astral.sh/uv/).

```bash
cd /home/mahdi/workspace/vitals
uv sync
```

فایل `.env` از قبل با کلید نشست تصادفی و هش رمز ساخته شده است. فقط دو کلید AvalAI را در آن بگذارید:

```bash
$EDITOR .env
```

```dotenv
AVALAI_PERSONAL_API_KEY=...
AVALAI_COMPANY_API_KEY=...
```

برای عوض کردن رمز عبور:

```bash
uv run python scripts/set_password.py
```

اجرای محلی (بدون Caddy) برای آزمایش:

```bash
VITALS_COOKIE_SECURE=false uv run uvicorn app.main:app \
  --host 127.0.0.1 --port 8010 --no-server-header
```

سپس `http://127.0.0.1:8010`. در حالت محلی حتماً `VITALS_COOKIE_SECURE=false` باشد، وگرنه مرورگر کوکی Secure را روی HTTP نمی‌فرستد.

## استقرار

### ۱. DNS

رکورد `A` (و در صورت نیاز `AAAA`) برای `vitals.m-hosseinpour.ir` باید به همین سرور اشاره کند:

```bash
dig +short vitals.m-hosseinpour.ir
```

تا وقتی این خروجی خالی است، Caddy نمی‌تواند گواهی بگیرد و سایت بالا نمی‌آید.

### ۲. Caddy

بلوک `deploy/Caddyfile` را به `/etc/caddy/Caddyfile` اضافه کنید و بعد:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

این بلوک TLS خودکار، هدرهای امنیتی، محدودیت ۶۴ کیلوبایتی بدنه و پروکسی به `127.0.0.1:8010` را تنظیم می‌کند.

### ۳. سرویس systemd کاربر

واحد سرویس در سطح کاربر ساخته و فعال شده است:

```bash
systemctl --user status vitals.service
journalctl --user -u vitals.service -f
```

برای نصب دوباره یا بعد از تغییر مسیر پروژه:

```bash
./deploy/install-service.sh
```

اگر سرویس باید بعد از خروج از حساب هم روشن بماند:

```bash
loginctl enable-linger "$USER"
```

(روی این سرور `Linger=yes` از قبل فعال است.)

## تغییر تنظیمات

بعد از هر تغییر در `.env`:

```bash
systemctl --user restart vitals.service
```

- **رمز عبور:** `uv run python scripts/set_password.py` و بعد restart. همه‌ی نشست‌های قبلی باطل می‌شوند.
- **کلید نشست:** مقدار `VITALS_SECRET_KEY` را با یک مقدار تصادفی عوض کنید؛ همه‌ی نشست‌ها باطل می‌شوند.
- **کلیدهای AvalAI:** مقدارها را در `.env` عوض و سرویس را restart کنید.

ساخت مقدار تصادفی برای `VITALS_SECRET_KEY`:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

## عیب‌یابی

| نشانه | علت محتمل | کار |
| --- | --- | --- |
| Caddy خطای 502 می‌دهد | سرویس بالا نیست یا روی پورت دیگری است | `systemctl --user status vitals` و `journalctl --user -u vitals` |
| گواهی TLS صادر نمی‌شود | DNS به این سرور اشاره نمی‌کند یا پورت ۸۰/۴۴۳ بسته است | `dig +short vitals.m-hosseinpour.ir` و `ss -ltn` |
| ورود می‌چرخد و برمی‌گردد به صفحه‌ی ورود | `VITALS_COOKIE_SECURE=true` روی HTTP | برای تست محلی `false` کنید |
| کارت «کلید تنظیم نشده» است | مقدار کلید خالی است | `.env` را پر و سرویس را restart کنید |
| کارت «نامشخص» با پیام خطاست | AvalAI پاسخ نداد یا کلید رد شد | پیام همان کارت را بخوانید؛ کلید را بررسی کنید |
| اعداد قدیمی‌اند | کش ۶۰ ثانیه‌ای یا خطای موقت | دکمه‌ی «به‌روزرسانی» |

## ساختار

```
app/
  main.py        مسیرها، میان‌افزارها و راه‌اندازی
  config.py      خواندن و اعتبارسنجی .env
  avalai.py      درخواست به AvalAI، تحلیل پاسخ و کش
  auth.py        Argon2، نشست و CSRF
  security.py    هدرهای امنیتی و محدودیت ورود
  formatting.py  قالب‌بندی تومان، زمان و تاریخ شمسی
  templates/     صفحه‌ی ورود و داشبورد
  static/        CSS، JS، فونت و آیکون
scripts/
  set_password.py
deploy/
  Caddyfile              بلوک Caddy
  vitals.service.in      قالب واحد systemd
  install-service.sh     نصب و فعال‌سازی سرویس کاربر
```

## محدودیت‌ها

- کش و محدودیت ورود در حافظه‌ی همان پروسه‌اند؛ این داشبورد برای یک کاربر و یک نمونه طراحی شده است.
- تعیین نوع بسته بر اساس `template_id` و نام بسته است (همان قاعده‌ی اسکریپت `avalai-credit.py`)؛ بسته‌ی ناشناخته زیر «سایر» می‌آید.
- اگر AvalAI فیلدهای پاسخ را تغییر دهد، داشبورد «نامشخص» نشان می‌دهد و عدد جعلی نمی‌سازد.
