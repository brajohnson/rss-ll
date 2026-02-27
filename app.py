from flask import Flask, render_template, request, Response
import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
from feedgen.feed import FeedGenerator
import requests
from urllib.parse import urljoin

app = Flask(__name__)

# --- CORE SCRAPER ---
async def scrape_website(url, item_selector, title_selector):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # Use a real user agent so sites don't block you as a bot
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        try:
            # 'domcontentloaded' is faster and avoids ad-related timeouts
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            
            # Scroll slightly to trigger any "lazy-loading" content
            await page.evaluate("window.scrollTo(0, 800)")
            await asyncio.sleep(1) 
            
            content = await page.content()
        except Exception as e:
            print(f"Scrape Warning: {e}")
            # Grabs whatever HTML was loaded before the timeout
            content = await page.content()
        finally:
            await browser.close()
        
        soup = BeautifulSoup(content, 'html.parser')
        fg = FeedGenerator()
        fg.title(f"RSS Feed: {url}")
        fg.link(href=url)
        fg.description("Generated via Visual RSS Builder")

        # Find items and build the XML
        for item in soup.select(item_selector)[:20]:
            title_el = item.select_one(title_selector)
            link_el = item.find('a', href=True)
            
            if title_el and link_el:
                fe = fg.add_entry()
                fe.title(title_el.get_text(strip=True))
                # Ensure the link is a full URL (not just /article/1)
                full_link = urljoin(url, link_el['href'])
                fe.link(href=full_link)
                fe.id(full_link)
        
        return fg.rss_str(pretty=True)

# --- ROUTES ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/preview')
def preview():
    target_url = request.args.get('url')
    if not target_url: return "Enter a URL"
    try:
        # Proxy the site and inject the visual selector script
        r = requests.get(target_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # Fix relative image/css links so preview looks correct
        for tag in soup.find_all(['link', 'script', 'img'], src=True):
            tag['src'] = urljoin(target_url, tag['src'])
        for tag in soup.find_all('link', href=True):
            tag['href'] = urljoin(target_url, tag['href'])

        injection = """
        <style>
            .rss-hover { outline: 2px dashed #ff6600 !important; cursor: crosshair !important; background: rgba(255,102,0,0.1) !important; }
            .selected-container { outline: 4px solid #28a745 !important; }
            .selected-title { outline: 4px solid #007bff !important; }
        </style>
        <script>
            document.addEventListener('mouseover', e => { e.target.classList.add('rss-hover'); e.stopPropagation(); });
            document.addEventListener('mouseout', e => { e.target.classList.remove('rss-hover'); e.stopPropagation(); });
            
            document.addEventListener('click', function(e) {
                e.preventDefault(); e.stopPropagation();
                let el = e.target;
                let sel = el.tagName.toLowerCase();
                
                // Try to find a unique ID or class
                if(el.id) sel = "#" + el.id;
                else if(el.className) {
                    let cls = [...el.classList].filter(c => !c.startsWith('rss-') && !c.startsWith('selected-'))[0];
                    if(cls) sel += "." + cls;
                }
                
                window.parent.postMessage({ type: 'SELECTOR', value: sel }, '*');
            }, true);
            
            window.addEventListener('message', function(e) {
                if(e.data.action === 'apply') {
                    let last = document.querySelector('.rss-hover');
                    if(last) last.classList.add(e.data.cls);
                }
            });
        </script>
        """
        return str(soup) + injection
    except Exception as e:
        return f"Preview Error: {e}"

# NEW: This is the URL you actually put into your RSS Reader
@app.route('/feed')
def serve_feed():
    url = request.args.get('url')
    item_css = request.args.get('item')
    title_css = request.args.get('title')
    
    if not all([url, item_css, title_css]):
        return "Missing RSS parameters", 400
        
    rss_data = asyncio.run(scrape_website(url, item_css, title_css))
    return Response(rss_data, mimetype='application/xml')

# Used by the 'Generate' button on the homepage
@app.route('/generate', methods=['POST'])
def generate():
    url = request.form.get('url')
    item_css = request.form.get('item_css')
    title_css = request.form.get('title_css')
    
    rss_data = asyncio.run(scrape_website(url, item_css, title_css))
    return Response(rss_data, mimetype='application/xml')

if __name__ == '__main__':
    app.run(debug=True)