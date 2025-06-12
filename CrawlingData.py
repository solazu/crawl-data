import asyncio
import logging
import re
from urllib.parse import urljoin, urlparse, parse_qs, urlencode

import httpx
from lxml import html
import tenacity
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# Các phần mở rộng file tĩnh, sẽ bỏ qua
EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".svg", ".ico",
              ".pdf", ".zip", ".rar", ".tar", ".gz", ".mp4",
              ".mp3", ".avi", ".wmv", ".doc", ".docx", ".xls", ".xlsx"}

# Các từ khóa cần loại bỏ trong URL
STOPWORDS = ["#", "/login", "/tai-khoan", "/account", "Warning", "@", "upload"]
STOPWORD_PATTERN = re.compile("|".join(map(re.escape, STOPWORDS)))

# Các pattern không hợp lệ
BAD_SCHEME_IN_PATH = re.compile(r"https?:/[^/]", re.IGNORECASE)
BAD_EMBEDDED = re.compile(r"https?://.*https?://", re.IGNORECASE)

# Các pattern ưu tiên cho trang sản phẩm
PRODUCT_PATTERNS = [
    # Tiếng Việt
    r"/san-pham/", r"/sanpham/", r"/sp/", r"/p/", r"/item/",
    r"/danh-muc/", r"/danhmuc/", r"/dm/", r"/c/", r"/category/",
    r"/thuong-hieu/", r"/thuonghieu/", r"/brand/", r"/nhan-hieu/",
    r"/nha-cung-cap/", r"/nhacungcap/", r"/supplier/", r"/vendor/",
    r"/merchant/", r"/seller/", r"/shop/", r"/store/", r"/cua-hang/",
    r"/cuahang/", r"/ch/", r"/collections/", r"/bo-suu-tap/",
    r"/bosuutap/", r"/bst/", r"/catalog/", r"/danh-sach/",
    r"/danhsach/", r"/ds/", r"/list/", r"/products/",

    # Rau củ quả
    r"/rau-cu-qua/", r"/rau-cu/", r"/rau-xanh/", r"/rau-sach/",
    r"/cu/", r"/rau/", r"/hoa-qua/", r"/trai-cay/", r"/trai-cay-tuoi/",
    r"/cam/", r"/muop/", r"/buoi/", r"/tao/", r"/xoai/", r"/nho/", r"/mit/",
    r"/dua-hau/", r"/khoai-tay/", r"/ca-chua/", r"/ca-rot/", r"/su-su/",
    r"/rau-muong/", r"/rau-diep-ca/", r"/rau-cai/", r"/rau-mam/",
    r"/rau-thom/", r"/rau-ngot/", r"/rau-dang/", r"/rau-ma/",
    r"/rau-den/", r"/rau-ngo/", r"/rau-dau/", r"/rau-cai-xanh/",
    r"/rau-cai-trang/", r"/rau-cai-thao/", r"/rau-cai-bap/",
    r"/rau-cai-lan/", r"/rau-cai-bap-xanh/", r"/rau-cai-bap-trang/",
    r"/rau-cai-bap-tim/", r"/rau-cai-bap-do/", r"/rau-cai-bap-vang/",
    r"/rau-cai-bap-cam/", r"/rau-cai-bap-xanh-la/", r"/rau-cai-bap-trang-la/",
    r"/rau-cai-bap-tim-la/", r"/rau-cai-bap-do-la/", r"/rau-cai-bap-vang-la/",
    r"/rau-cai-bap-cam-la/",

    # Thịt cá
    r"/thit-ca/", r"/thit/", r"/ca/", r"/thit-tuoi/", r"/thit-lon/",
    r"/thit-heo/", r"/thit-bo/", r"/thit-ga/", r"/thit-vit/",
    r"/thit-ngan/", r"/thit-ngong/", r"/thit-de/", r"/thit-dau/",
    r"/thit-cu/", r"/thit-xay/", r"/thit-bam/", r"/thit-lon-xay/",
    r"/thit-heo-xay/", r"/thit-bo-xay/", r"/thit-ga-xay/",
    r"/thit-vit-xay/", r"/thit-ngan-xay/", r"/thit-ngong-xay/",
    r"/thit-de-xay/", r"/thit-dau-xay/", r"/thit-cu-xay/",
    r"/thit-lon-bam/", r"/thit-heo-bam/", r"/thit-bo-bam/",
    r"/thit-ga-bam/", r"/thit-vit-bam/", r"/thit-ngan-bam/",
    r"/thit-ngong-bam/", r"/thit-de-bam/", r"/thit-dau-bam/",
    r"/thit-cu-bam/",

    # Hải sản
    r"/hai-san/", r"/hai-san-tuoi/", r"/hai-san-dong-lanh/",
    r"/tom/", r"/ca-hoi/", r"/ca-basa/", r"/ca-loc/", r"/ca-chep/",
    r"/ca-ro/", r"/ca-tram/", r"/ca-linh/", r"/ca-linh-ho/",
    r"/ca-linh-bong/", r"/ca-linh-dau/", r"/ca-linh-cu/",
    r"/ca-linh-xay/", r"/ca-linh-bam/", r"/ca-linh-tuoi/",
    r"/ca-linh-dong-lanh/", r"/ca-linh-kho/", r"/ca-linh-nuong/",
    r"/ca-linh-chien/", r"/ca-linh-luoc/", r"/ca-linh-hap/",
    r"/ca-linh-nau/", r"/ca-linh-xao/", r"/ca-linh-lam/",
    r"/ca-linh-ran/", r"/ca-linh-nuong/", r"/ca-linh-chien/",
    r"/ca-linh-luoc/", r"/ca-linh-hap/", r"/ca-linh-nau/",
    r"/ca-linh-xao/", r"/ca-linh-lam/", r"/ca-linh-ran/",

    # Đồ uống
    r"/do-uong/", r"/nuoc-giai-khat/", r"/tra/", r"/cafe/",
    r"/bia-ruou/", r"/ruou/", r"/nuoc-ep/", r"/nuoc-cam/",
    r"/nuoc-dua/", r"/nuoc-dua-hau/", r"/nuoc-dua-non/",
    r"/nuoc-dua-tuoi/", r"/nuoc-dua-dong-lanh/", r"/nuoc-dua-kho/",
    r"/nuoc-dua-nuong/", r"/nuoc-dua-chien/", r"/nuoc-dua-luoc/",
    r"/nuoc-dua-hap/", r"/nuoc-dua-nau/", r"/nuoc-dua-xao/",
    r"/nuoc-dua-lam/", r"/nuoc-dua-ran/", r"/nuoc-dua-nuong/",
    r"/nuoc-dua-chien/", r"/nuoc-dua-luoc/", r"/nuoc-dua-hap/",
    r"/nuoc-dua-nau/", r"/nuoc-dua-xao/", r"/nuoc-dua-lam/",
    r"/nuoc-dua-ran/",

    # Bánh kẹo
    r"/banh-keo/", r"/bim-sua/", r"/my-goi/", r"/bot-an/",
    r"/gia-vi/", r"/dau-an/", r"/kem-tuoi/", r"/sua-tuoi/",
    r"/sua-bot/", r"/pho-mat/", r"/banh-quy/", r"/banh-ngot/",
    r"/banh-man/", r"/banh-trang/", r"/banh-trang-tron/",
    r"/banh-trang-cuon/", r"/banh-trang-nuong/", r"/banh-trang-chien/",
    r"/banh-trang-luoc/", r"/banh-trang-hap/", r"/banh-trang-nau/",
    r"/banh-trang-xao/", r"/banh-trang-lam/", r"/banh-trang-ran/",
    r"/banh-trang-nuong/", r"/banh-trang-chien/", r"/banh-trang-luoc/",
    r"/banh-trang-hap/", r"/banh-trang-nau/", r"/banh-trang-xao/",
    r"/banh-trang-lam/", r"/banh-trang-ran/",

    # Tiếng Anh
    r"/product/", r"/products/", r"/item/", r"/items/",
    r"/category/", r"/categories/", r"/cat/", r"/catalog/",
    r"/catalogs/", r"/collection/", r"/collections/", r"/coll/",
    r"/brand/", r"/brands/", r"/supplier/", r"/suppliers/",
    r"/vendor/", r"/vendors/", r"/merchant/", r"/merchants/",
    r"/seller/", r"/sellers/", r"/shop/", r"/shops/",
    r"/store/", r"/stores/", r"/list/", r"/lists/",
    
    # Pattern số
    r"/[0-9]+/", r"/p[0-9]+/", r"/sp[0-9]+/", r"/item[0-9]+/",
    r"/product[0-9]+/", r"/pr[0-9]+/", r"/pd[0-9]+/"
]

# Pattern cho phân trang
PAGINATION_PATTERNS = [
    r"page=", r"p=", r"trang=", r"page_num=",
    r"pagenum=", r"page-number=", r"page_number=",
    r"pageNum=", r"page_num=", r"pageNumber=",
    r"page_number=", r"pageIndex=", r"page_index=",
    r"pageIndex=", r"page_index=", r"pageSize=",
    r"page_size=", r"limit=", r"offset="
]

PRODUCT_PATTERN = re.compile("|".join(PRODUCT_PATTERNS), re.IGNORECASE)
PAGINATION_PATTERN = re.compile("|".join(PAGINATION_PATTERNS), re.IGNORECASE)
DYNAMIC_THRESHOLD = 50

logging.basicConfig(level=logging.INFO)

@tenacity.retry(
    wait=tenacity.wait_exponential(multiplier=1, min=1, max=5),
    stop=tenacity.stop_after_attempt(2),
    reraise=True,
    retry=tenacity.retry_if_exception_type((httpx.HTTPStatusError, httpx.RequestError, httpx.TimeoutException))
)
async def fetch(client: httpx.AsyncClient, url: str) -> str:
    try:
        resp = await client.get(url, timeout=10.0)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        logging.warning(f"[!] HTTP error {url}: {e}")
        return ""

async def fetch_rendered_hrefs(url: str) -> list[str]:
    """Dùng Playwright để load JS, trả về list href động."""
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={'width': 1280, 'height': 720},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            )
            page = await context.new_page()
            
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                # Thêm delay nhỏ để đảm bảo JS load xong
                await page.wait_for_timeout(1000)
                hrefs = await page.eval_on_selector_all("a", "anchors => anchors.map(a=>a.href)")
            except PlaywrightTimeoutError:
                logging.warning(f"[!] Playwright timeout for {url}")
                hrefs = []
            finally:
                await context.close()
                await browser.close()
            return hrefs
    except Exception as e:
        logging.warning(f"[!] Playwright error {url}: {e}")
        return []

def normalize_url(base: str, href: str) -> str:
    href = href.split("#")[0]
    if href.startswith(("http://", "https://")):
        return href.rstrip("/")
    return urljoin(base, href).rstrip("/")

def is_valid(link: str, base_netloc: str) -> bool:
    if not link.startswith(("http://", "https://")):
        return False
    parsed = urlparse(link)
    if parsed.netloc != base_netloc:
        return False
    if BAD_SCHEME_IN_PATH.search(parsed.path):
        return False
    if STOPWORD_PATTERN.search(link):
        return False
    path = parsed.path.lower()
    if any(path.endswith(ext) for ext in EXTENSIONS):
        return False
    if re.search(r"\d{7,}", path):
        return False
    return True

def is_product_page(url: str) -> bool:
    """Kiểm tra xem URL có phải là trang sản phẩm không"""
    return bool(PRODUCT_PATTERN.search(url))

def is_pagination_page(url: str) -> bool:
    """Kiểm tra xem URL có phải là trang phân trang không"""
    return bool(PAGINATION_PATTERN.search(url))

def get_pagination_urls(url: str, max_pages: int = 20) -> list[str]:
    """Tạo các URL phân trang từ URL gốc"""
    urls = []
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    
    # Tìm tham số phân trang
    page_param = None
    for param in query.keys():
        if PAGINATION_PATTERN.search(param):
            page_param = param
            break
    
    if page_param:
        # Tạo các URL phân trang
        for page in range(1, max_pages + 1):
            query[page_param] = [str(page)]
            new_query = urlencode(query, doseq=True)
            new_url = parsed._replace(query=new_query).geturl()
            urls.append(new_url)
    
    return urls

async def crawl(domain: str, max_pages: int = 2000, concurrency: int = 20):
    parsed0 = urlparse(domain)
    base = f"{parsed0.scheme}://{parsed0.netloc}"
    seen = {base}
    product_links = set()  # Tập hợp các link sản phẩm
    queue = asyncio.Queue()
    queue.put_nowait(base)

    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(
        limits=limits, 
        follow_redirects=True,
        timeout=10.0,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
    ) as client:
        sem = asyncio.Semaphore(concurrency)

        async def worker():
            while not queue.empty() and len(seen) < max_pages:
                url = await queue.get()
                async with sem:
                    try:
                        page_html = await fetch(client, url)
                    except Exception as e:
                        logging.warning(f"[!] Fetch error {url}: {e}")
                        continue

                hrefs = set()
                # Trích cả href và src từ HTML tĩnh
                if page_html:
                    doc = html.fromstring(page_html)
                    hrefs.update(doc.xpath("//a/@href"))
                    hrefs.update(doc.xpath("//*[@src]/@src"))

                # 2) Dynamic parsing nếu trang này có ít anchor (< threshold)
                if len(hrefs) < DYNAMIC_THRESHOLD or url == base:
                    dynamic = await fetch_rendered_hrefs(url)
                    hrefs.update(dynamic)

                # 3) Xử lý từng href
                for raw in hrefs:
                    norm = normalize_url(base, raw)
                    if norm not in seen and is_valid(norm, parsed0.netloc):
                        seen.add(norm)
                        if is_product_page(norm):
                            product_links.add(norm)
                            logging.info(f"[+] Found product page: {norm}")
                        # Thêm các trang phân trang vào queue
                        if is_pagination_page(norm):
                            pagination_urls = get_pagination_urls(norm)
                            for pag_url in pagination_urls:
                                if pag_url not in seen:
                                    seen.add(pag_url)
                                    await queue.put(pag_url)
                                    logging.info(f"[+] Added pagination page: {pag_url}")
                        await queue.put(norm)
                        logging.info(f"[+] New link: {norm}")

                queue.task_done()

        tasks = [asyncio.create_task(worker()) for _ in range(concurrency)]
        await queue.join()
        for t in tasks:
            t.cancel()

    return sorted(product_links)  # Trả về danh sách các link sản phẩm

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Crawl domain và bao gồm cả link JS-generated")
    parser.add_argument("domain", nargs="?", help="Ví dụ: https://bachhoaxanh.com")
    parser.add_argument("--max-pages", type=int, default=2000)  # Tăng số trang mặc định
    parser.add_argument("--concurrency", type=int, default=20)
    args = parser.parse_args()

    if not args.domain:
        args.domain = input("Nhập domain (https://...): ").strip()

    results = asyncio.run(crawl(
        args.domain,
        max_pages=args.max_pages,
        concurrency=args.concurrency
    ))
    print(f"Found {len(results)} product links:")
    for u in results:
        print(u)
