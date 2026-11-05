# ویتالز

داشبورد کوچک و رمزدار برای دیدن وضعیت سرویس‌ها در یک صفحه. هر بخش داده‌های خودش را سمت سرور می‌خواند؛ کلیدها و رازها هیچ‌وقت به مرورگر نمی‌رسند.

## بخش فعلی: اعتبار AvalAI

بخش فعلی دو حساب AvalAI را نشان می‌دهد:

- حساب اول (`AVALAI_PERSONAL_API_KEY`)
- حساب دوم (`AVALAI_COMPANY_API_KEY`)

برچسب کارت‌ها با `AVALAI_PERSONAL_LABEL` و `AVALAI_COMPANY_LABEL` قابل تغییر است. هر حساب مستقل خوانده می‌شود؛ اگر یکی از کلیدها تنظیم نشده باشد یا سرویس پاسخ ندهد، حساب دیگر سالم می‌ماند.

برای هر حساب:

- هر بسته‌ی فعال در یک کارت جداگانه با موجودی، درصد مصرف و زمان باقی‌مانده
- ترتیب بسته‌ها بر اساس نزدیک‌ترین پایان
- اعتبار اصلی در یک کارت جداگانه بعد از بسته‌ها
- وضعیت: بسته‌های فعال، مصرف از اعتبار اصلی، تمام‌شده، یا نامشخص
- هشدار برای بسته‌های منقضی‌شده‌ای که هنوز موجودی دارند
- دکمه‌ی «خرید بسته» در نوار بالا که فروشگاه بسته‌های AvalAI را در تب جدید باز می‌کند

اعداد از پاسخ `GET https://api.avalai.ir/user/v1/credit` خوانده می‌شوند. مقدارها به تومان‌اند و فقط سمت سرور پردازش می‌شوند.

## امنیت

- در استقرار پیشنهادی، TLS و گواهی خودکار با Caddy؛ برنامه به‌طور پیش‌فرض فقط روی `127.0.0.1:8010` گوش می‌دهد.
- رمز عبور با **Argon2id** هش می‌شود؛ متن رمز در هیچ فایلی ذخیره نمی‌شود.
- نشست با کوکی امضاشده و پرچم‌های `HttpOnly` و `SameSite=Lax`. در حالت HTTPS نام کوکی `__Host-vitals` و پرچم `Secure` دارد؛ در اجرای HTTP محلی نام آن `vitals_session` است.
- توکن CSRF برای ورود و خروج؛ نشست در زمان ورود کامل بازنشانی می‌شود.
- محدودیت تلاش ورود: ۵ تلاش ناموفق در ۱۰ دقیقه ← ۱۵ دقیقه قفل برای همان IP.
- هدرهای امنیتی: CSP بدون inline، `frame-ancestors 'none'`، `nosniff`، HSTS، `Referrer-Policy` و `Permissions-Policy`.
- `TrustedHost` برای رد Hostهای ناشناخته؛ بدنه‌ی فرم‌ها محدود به ۴ کیلوبایت است.
- سرویس systemd نمونه با `ProtectSystem=strict`، `ProtectHome=read-only`، `NoNewPrivileges` و `PrivateTmp` اجرا می‌شود.
- فونت وزیرمتن و همه‌ی دارایی‌ها self-host هستند؛ هیچ درخواستی به CDN یا سرویس خارجی زده نمی‌شود.
- خطاهای سرویس بیرونی به‌صورت پیام کوتاه و بدون افشای کلید یا بدنه‌ی پاسخ نمایش داده می‌شوند.
- داده‌ها ۶۰ ثانیه کش می‌شوند تا هر بار باز شدن صفحه به سرویس بیرونی فشار نیاورد؛ خطا هم ۱۲۰ ثانیه به خاطر سپرده می‌شود.

## راه‌اندازی

پیش‌نیاز: Python 3.12 یا جدیدتر و [uv](https://docs.astral.sh/uv/). پروژه را در مسیر دلخواه قرار دهید و وارد پوشه شوید:

```bash
cd ~/vitals
uv sync
cp .env.example .env
chmod 600 .env
```

کلید نشست را بسازید و در `.env` بگذارید:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

هش رمز عبور را با Argon2 بسازید:

```bash
uv run python scripts/set_password.py
```

بعد کلیدهای AvalAI و میزبان‌های مجاز را تنظیم کنید:

```bash
$EDITOR .env
```

```dotenv
AVALAI_PERSONAL_API_KEY=...
AVALAI_COMPANY_API_KEY=...
VITALS_ALLOWED_HOSTS=localhost,127.0.0.1
```

اگر از دامنه یا IP مشخصی استفاده می‌کنید، آن را هم به `VITALS_ALLOWED_HOSTS` اضافه کنید.

### اجرای محلی

```bash
VITALS_COOKIE_SECURE=false uv run uvicorn app.main:app \
  --host 127.0.0.1 --port 8010 --no-server-header
```

سپس `http://127.0.0.1:8010`. در حالت HTTP حتماً `VITALS_COOKIE_SECURE=false` باشد، وگرنه مرورگر کوکی `Secure` را نمی‌فرستد.

### دسترسی از دستگاه دیگر، بدون دامنه

اگر فقط خودتان از راه دور نیاز دارید، امن‌ترین راه تونل SSH است و نیازی به باز کردن پورت روی اینترنت ندارد:

```bash
ssh -L 8010:127.0.0.1:8010 user@server
```

بعد در مرورگر خودتان `http://127.0.0.1:8010` را باز کنید.

اگر در شبکه‌ی خصوصی یا VPN هستید و TLS ندارید، می‌توانید برنامه را روی آدرس شبکه باز کنید:

```bash
VITALS_COOKIE_SECURE=false \
VITALS_ALLOWED_HOSTS=192.168.1.10,localhost,127.0.0.1 \
uv run uvicorn app.main:app --host 0.0.0.0 --port 8010 --no-server-header
```

این حالت رمز عبور و نشست را روی HTTP بدون رمزنگاری می‌فرستد؛ فقط در شبکه‌ی مورد اعتماد استفاده کنید. برای دسترسی عمومی، HTTP خام را باز نکنید.

## استقرار با دامنه و Caddy

اگر می‌خواهید از اینترنت با یک دامنه در دسترس باشد:

### ۱. DNS

رکورد `A` (و در صورت نیاز `AAAA`) دامنه را به سرور اشاره دهید:

```text
vitals.example.com.  A  203.0.113.10
```

```bash
dig +short vitals.example.com
```

تا وقتی این خروجی خالی است، Caddy نمی‌تواند گواهی بگیرد.

### ۲. Caddy

بلوک `deploy/Caddyfile` را به `/etc/caddy/Caddyfile` اضافه کنید، `vitals.example.com` را با دامنه‌ی خودتان عوض کنید و بعد:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

این بلوک TLS خودکار، هدرهای امنیتی، محدودیت ۶۴ کیلوبایتی بدنه و پروکسی به `127.0.0.1:8010` را تنظیم می‌کند.

اگر دامنه ندارید، Caddy را مجبور به HTTPS با گواهی عمومی نکنید؛ از تونل SSH، VPN یا یک reverse proxy با گواهی معتبر استفاده کنید.

### ۳. سرویس systemd کاربر

```bash
./deploy/install-service.sh
systemctl --user status vitals.service
journalctl --user -u vitals.service -f
```

اگر سرویس باید بعد از خروج از حساب هم روشن بماند:

```bash
loginctl enable-linger "$USER"
```

اگر systemd کاربری در دسترس نیست، همین `ExecStart` را در یک unit سیستمی با `User=` و `WorkingDirectory=` مناسب قرار دهید.

## تغییر تنظیمات

بعد از هر تغییر در `.env`:

```bash
systemctl --user restart vitals.service
```

- **رمز عبور:** `uv run python scripts/set_password.py` و بعد restart. همه‌ی نشست‌های قبلی باطل می‌شوند.
- **کلید نشست:** مقدار `VITALS_SECRET_KEY` را با یک مقدار تصادفی عوض کنید؛ همه‌ی نشست‌ها باطل می‌شوند.
- **کلیدهای AvalAI:** مقدارها را در `.env` عوض و سرویس را restart کنید.
- **نام کارت‌ها:** `AVALAI_PERSONAL_LABEL` و `AVALAI_COMPANY_LABEL`.
- **لینک خرید بسته:** `AVALAI_PACKAGES_URL`؛ پیش‌فرض فروشگاه بسته‌های AvalAI است.

## عیب‌یابی

| نشانه | علت محتمل | کار |
| --- | --- | --- |
| Caddy خطای 502 می‌دهد | سرویس بالا نیست یا روی پورت دیگری است | `systemctl --user status vitals` و `journalctl --user -u vitals` |
| گواهی TLS صادر نمی‌شود | DNS به این سرور اشاره نمی‌کند یا پورت ۸۰/۴۴۳ بسته است | `dig +short vitals.example.com` و `ss -ltn` |
| خطای 400 یا «Host مجاز نیست» | دامنه یا IP در `VITALS_ALLOWED_HOSTS` نیست | آن را به `.env` اضافه و سرویس را restart کنید |
| ورود می‌چرخد و برمی‌گردد به صفحه‌ی ورود | `VITALS_COOKIE_SECURE=true` روی HTTP | برای اجرای محلی `false` کنید |
| کارت «تنظیم نشده» است | مقدار کلید خالی است | `.env` را پر و سرویس را restart کنید |
| کارت «نامشخص» با پیام خطاست | AvalAI پاسخ نداد یا کلید رد شد | پیام همان کارت را بخوانید؛ کلید را بررسی کنید |
| اعداد قدیمی‌اند | کش ۶۰ ثانیه‌ای یا خطای موقت | دکمه‌ی «به‌روزرسانی» |

## ساختار

```text
app/
  main.py        مسیرها، میان‌افزارها و راه‌اندازی
  config.py      خواندن و اعتبارسنجی .env
  avalai.py      درخواست به AvalAI، تحلیل پاسخ و کش
  auth.py        Argon2، نشست و CSRF
  security.py    هدرهای امنیتی و محدودیت ورود
  formatting.py  قالب‌بندی تومان و زمان
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
- اگر AvalAI فیلدهای پاسخ را تغییر دهد، داشبورد «نامشخص» نشان می‌دهد و عدد جعلی نمی‌سازد.
