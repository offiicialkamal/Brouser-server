from flask import Flask, request, Response, make_response
import requests
import re                                                                                                                                               
import logging
from urllib.parse import urlparse, urljoin, parse_qs, quote, unquote
import time

app = Flask(__name__)
app.logger.setLevel(logging.DEBUG)

# Use a realistic User-Agent string
REALISTIC_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/110.0.0.0 Safari/537.36")
REQUEST_TIMEOUT = 20  # seconds

def add_base_tag(html_content, base_url):
    if "<base" in html_content.lower():
        return html_content
    base_tag = f'<base href="{base_url}" target="_self">'
    return re.sub(r'(<head.*?>)', r'\1' + base_tag, html_content, count=1, flags=re.IGNORECASE)

def rewrite_anchor_links(html_content, base_url):
    parsed_base = urlparse(base_url)
    base_domain = f"{parsed_base.scheme}://{parsed_base.netloc}"
    encoded_base = quote(base_url, safe='')

    def replace_anchor(match):
        prefix = match.group(1)
        url_part = match.group(2)
        quote_char = match.group(3)
        if url_part.startswith("http"):
            full_url = url_part
        else:                                                                                                                                                       
            full_url = urljoin(base_domain, url_part)
            encoded_url = quote(full_url, safe='')
        return f'{prefix}href={quote_char}/proxy?url={encoded_url}&base={encoded_base}{quote_char}'
    
    pattern = r'(<a\s+[^>]*?)href=(["\'])([^"\']+)(["\'])'
    return re.sub(pattern, replace_anchor, html_content, flags=re.IGNORECASE)

def rewrite_resource_urls(html_content, base_url):
    parsed_base = urlparse(base_url)
    base_domain = f"{parsed_base.scheme}://{parsed_base.netloc}"
    encoded_base = quote(base_url, safe='')

    def replace_resource(match):
        attr, quote_char, url_part = match.groups()
        if url_part.startswith("http"):
            full_url = url_part
        else:
            full_url = urljoin(base_domain, url_part)
        encoded_url = quote(full_url, safe='')                                                                                                                  
        return f'{attr}{quote_char}/proxy?url={encoded_url}&base={encoded_base}{quote_char}'

    pattern = r'(src=|href=)(["\'])(?!/proxy)(https?://[^"\']+|/[^"\']+)'
    return re.sub(pattern, replace_resource, html_content, flags=re.IGNORECASE)

def modify_html(html_content, base_url):
    html_content = add_base_tag(html_content, base_url)
    html_content = rewrite_anchor_links(html_content, base_url)
    html_content = rewrite_resource_urls(html_content, base_url)
    return html_content
    
def isURL(url):
    try:
        for prefixOrSuffix in ['https://', 'http://', '.com','.in','.gov','.online']:
           if prefixOrSuffix in url:
            #   print('its an url')
               return True
              # break
        #   else:
        #       print('no its not url ! its a search qury')
        #       time.sleep(2)
        
        return False
            
        # isUrlResponse = requests.get(url)
        # if isUrlResponse.status_code != 200 or isUrlResponse.status_code == 404:
        #     return False
        # else:
        #     return True
    except Exception as e:
        print(e)
        
        
@app.route('/proxy')
def proxy():
    url = request.args.get('url')
    base_param = request.args.get('base')
    if not url:
        app.logger.error("No URL provided in /proxy request.")
        return "<h3>Error: No URL provided.</h3>", 400

    if isURL(url):
        print(f'yess thats a url {url}')
    else:
        print('its not a url its a search quirey searching on Google.com')
        #once confirmed its a search query lets pass the querie on google search URL
        url = f'https://www.google.com/search?q={url}'
            
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
        
        
    app.logger.debug(f"Proxying URL: {url}")
    try:
        response = requests.get(url, headers={'User-Agent': REALISTIC_UA,'Accept-Language': 'en-US,en;q=0.9'},stream=True, timeout=REQUEST_TIMEOUT)
        # Optionally intercept redirects if needed:
        if 300 <= response.status_code < 400 and 'Location' in response.headers:
            location = response.headers['Location']
            if not location.startswith(('http://', 'https://')):
                location = urljoin(url, location)
            encoded_location = quote(location, safe='')
            app.logger.debug(f"Intercepted redirect to: {location}")
            return Response(f'<html><head><meta http-equiv="refresh" content="0;url=/proxy?url={encoded_location}"></head><body>Redirecting...</body></html>',content_type='text/html')
        
        
        
        content_type = response.headers.get('Content-Type', '')
        
        if 'text/html' in content_type:
            html = response.text
            modified_html = modify_html(html, url)
            resp = make_response(Response(modified_html, content_type='text/html'))
            if base_param:
                base_for_cookie = unquote(base_param)
            else:
                parsed = urlparse(url)
                base_for_cookie = f"{parsed.scheme}://{parsed.netloc}"
            resp.set_cookie("proxy_base", base_for_cookie, max_age=3600)
            return resp
        return Response(response.content, content_type=content_type)
    except requests.exceptions.RequestException as e:
        app.logger.exception("Error fetching URL:")
        return f"<h3>Error fetching URL: {str(e)}</h3>", 500

@app.route('/<path:subpath>')
def catch_all(subpath):
    referer = request.headers.get('Referer')
    if not referer:
        app.logger.error("No Referer header found in catch_all route.")
        return "<h3>Error: No Referer header found. Cannot determine base URL.</h3>", 404

    parsed_ref = urlparse(referer)
    ref_query = parse_qs(parsed_ref.query)
    base_url = ref_query.get('base', [None])[0]
    if not base_url:
        base_url = ref_query.get('url', [None])[0]
    if not base_url:
        base_url = request.cookies.get("proxy_base")
    if not base_url:
        base_url = f"{parsed_ref.scheme}://{parsed_ref.netloc}"
        app.logger.warning("Falling back to referer's scheme and netloc as base URL.")

    app.logger.debug(f"Catch-all route: base_url determined as {base_url}")
    full_url = urljoin(base_url, '/' + subpath)
    app.logger.debug(f"Reconstructed full URL: {full_url}")
    try:
        resp = requests.get(full_url, headers={'User-Agent': REALISTIC_UA,
                                                 'Accept-Language': 'en-US,en;q=0.9'},
                            stream=True, timeout=REQUEST_TIMEOUT)
        content_type = resp.headers.get('Content-Type', '')
        return Response(resp.content, content_type=content_type)
    except requests.exceptions.RequestException as e:
        app.logger.exception("Error fetching resource:")
        return f"<h3>Error fetching resource: {str(e)}</h3>", 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
