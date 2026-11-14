# Megan-shared-memory

مخزن توسعه سامانه Megan برای کشف و تحلیل میم‌کوین‌ها و شت‌کوین‌ها؛ نسخه نخست فقط روی Ethereum متمرکز است.

## اسناد پروژه
- [چارچوب تحلیل فارسی](MEMECOIN_ANALYSIS_FRAMEWORK_FA.md)
- [نقشه راه Ethereum](docs/ROADMAP_ETHEREUM_MEMECOIN_ANALYZER_FA.md)
- [برنامه اجرایی](docs/IMPLEMENTATION_PLAN_FA.md)

## کد فعلی
- [هسته کشف قرارداد و استخر](src/megan_watcher.py)
- [تنظیمات Python](pyproject.toml)
- [نمونه متغیرهای محیطی](.env.example)
- [تست‌های خودکار](tests/)
- [GitHub Actions](.github/workflows/tests.yml)

## قابلیت‌های MVP
- اتصال فقط‌خواندنی به Ethereum Mainnet از طریق JSON-RPC.
- پیمایش بلوک‌ها با فاصله تأیید قابل تنظیم.
- شناسایی قراردادهای تازه‌مستقرشده مستقیم و قراردادهای داخلی CREATE/CREATE2 با APIهای trace در Geth یا Erigon (در صورت پشتیبانی RPC).
- ثبت جداگانه وضعیت پوشش trace هر بلوک؛ نبود API trace به‌عنوان پوشش کامل گزارش نمی‌شود.
- شناسایی رویدادهای ایجاد استخر V2-style و V3-style با decoderهای آزمون‌پذیر.
- پایش رویداد ایجاد استخر در factoryهای V2-style و V3-style که آدرسشان در تنظیمات وارد شده باشد.
- ذخیره توکن‌ها، استخرها، رویدادها و cursor پردازش در SQLite.
- ادامه پردازش از آخرین بلوک ذخیره‌شده پس از راه‌اندازی مجدد.
- بدون کلید خصوصی، امضای تراکنش یا معامله خودکار.

## نصب و اجرا
Python 3.11 یا بالاتر لازم است.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

مقدار `ETHEREUM_RPC_URL` را در `.env` وارد کنید. برای کشف قراردادهای داخلی، RPC باید حداقل یکی از `trace_block` در Erigon یا `debug_traceBlockByNumber` با `callTracer` در Geth را ارائه کند. `TRACE_MODE=auto` هر دو را به‌ترتیب امتحان می‌کند. آدرس factoryها اختیاری‌اند؛ فقط آدرس‌های تأییدشده و متعلق به Ethereum Mainnet را تنظیم کنید.

```bash
megan-watch
```

برای اسکن بلوک‌های واجد تأیید و خروج:

```bash
megan-watch --once
```

برای اسکن تاریخی از بلوک مشخص، `START_BLOCK` را تنظیم کنید. اگر خالی باشد، برنامه از نوک واجد تأیید در زمان شروع آغاز می‌کند.

## آزمون

```bash
pip install -e ".[dev]"
pytest -q
```

هر push به `main` و هر pull request به‌صورت خودکار تست‌ها را در GitHub Actions اجرا می‌کند.

## محدودیت‌های مهم
این نسخه فقط کشف اولیه انجام می‌دهد و هنوز موتور امتیازدهی، تحلیل عمیق bytecode، تشخیص honeypot، گراف کیف‌پول، تحلیل کامل هولدرها، ردیابی Bonding Curve، قیمت‌گذاری و داشبورد ندارد. تشخیص ERC-20 heuristic است. فقط factoryهای پیکربندی‌شده پوشش داده می‌شوند. اگر RPC هیچ API trace نداشته باشد و `TRACE_REQUIRED=false` باشد، watcher ادامه می‌دهد اما آن بلوک را با وضعیت `unavailable` ثبت می‌کند؛ برای جلوگیری از عبور از بلوک‌های فاقد trace، `TRACE_REQUIRED=true` را فعال کنید. تعداد تأیید، احتمال reorg را کاهش می‌دهد اما نسخه فعلی rollback خودکار زنجیره‌ای ندارد. این برنامه هنوز پیش از آزمون و بازبینی برای استفاده عملیاتی آماده نیست.

**امنیت:** RPC URL ممکن است کلید API داشته باشد؛ `.env` را commit نکنید. کلید خصوصی کیف‌پول وارد برنامه نکنید.
