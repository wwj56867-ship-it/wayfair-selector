import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from scorer import ProductScorer, KeywordExtractor
from bs4 import BeautifulSoup
import time
import re
import json

try:
    from scraper import WayfairScraper
    SCRAPER_AVAILABLE = True
except Exception:
    SCRAPER_AVAILABLE = False

CLOUD_MODE = not SCRAPER_AVAILABLE


st.set_page_config(
    page_title="Wayfair 选品分析系统",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("🎯 Wayfair 跨境电商选品分析系统")
st.markdown("---")

_removed_weight_keys = [f'weight_{k}' for k in ['profit_margin_score', 'competition_score', 'name_length_score', 'market_opportunity_score', 'supply_scarcity_score', 'shipping_advantage_score']]
for _rk in _removed_weight_keys:
    if _rk in st.session_state:
        del st.session_state[_rk]

if 'custom_weights' in st.session_state:
    _valid_keys = set(ProductScorer.DEFAULT_WEIGHTS.keys())
    _current_keys = set(st.session_state.custom_weights.keys())
    if _current_keys != _valid_keys:
        del st.session_state.custom_weights

if 'products_data' not in st.session_state:
    st.session_state.products_data = None

if 'analyzed_data' not in st.session_state:
    st.session_state.analyzed_data = None
else:
    if st.session_state.analyzed_data is not None:
        removed_cols = {'profit_margin_score', 'competition_score', 'name_length_score', 'market_opportunity_score', 'supply_scarcity_score', 'shipping_advantage_score'}
        if removed_cols & set(st.session_state.analyzed_data.columns):
            st.session_state.analyzed_data = None


def extract_wayfair_html(html_content):
    products = []
    soup = BeautifulSoup(html_content, 'html.parser')

    page_category = ''
    page_breadcrumb = []

    breadcrumb_nav = soup.select_one('nav[aria-label="Breadcrumb"]')
    if breadcrumb_nav:
        links = breadcrumb_nav.find_all('a')
        for link in links:
            text = link.get_text(strip=True)
            if text and text.lower() not in ['home', 'wayfair']:
                page_breadcrumb.append(text)
        if page_breadcrumb:
            page_category = page_breadcrumb[-1]

    if not page_breadcrumb:
        for ol in soup.select('ol[class*="Breadcrumb"], ol[class*="breadcrumb"], ul[class*="Breadcrumb"], ul[class*="breadcrumb"]'):
            links = ol.find_all('a')
            for link in links:
                text = link.get_text(strip=True)
                if text and text.lower() not in ['home', 'wayfair']:
                    page_breadcrumb.append(text)
            if page_breadcrumb:
                page_category = page_breadcrumb[-1]
                break

    if not page_breadcrumb:
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                items = []
                if isinstance(data, dict) and data.get('@type') == 'BreadcrumbList':
                    items = data.get('itemListElement', [])
                elif isinstance(data, list):
                    for entry in data:
                        if isinstance(entry, dict) and entry.get('@type') == 'BreadcrumbList':
                            items = entry.get('itemListElement', [])
                            break
                for item in items:
                    name = item.get('name', '')
                    if name and name.lower() not in ['home', 'wayfair']:
                        page_breadcrumb.append(name)
                if page_breadcrumb:
                    page_category = page_breadcrumb[-1]
                    break
            except Exception:
                continue

    if not page_category:
        h1 = soup.find('h1')
        if h1:
            h1_text = h1.get_text(strip=True)
            if h1_text and len(h1_text) < 100:
                page_category = h1_text

    if not page_category:
        cat_match = re.search(r'/cat/([a-zA-Z0-9\-]+)', html_content)
        if cat_match:
            cat_slug = cat_match.group(1)
            cat_slug = re.sub(r'-c\d+$', '', cat_slug)
            page_category = cat_slug.replace('-', ' ').title()

    hurry_map = {}
    for m in re.finditer(
        r'<strong>(Better\s+Hurry|Selling\s+Quickly)</strong>\s*(\d+)\s*sold\s*<span[^>]*>in\s*(\d+)\s*days?</span>.*?aria-label="([^"]+?)"',
        html_content, re.IGNORECASE | re.DOTALL
    ):
        label = m.group(1).strip()
        sold_count = int(m.group(2))
        sold_days = int(m.group(3))
        product_name = m.group(4).strip()
        hurry_map[product_name] = {'sold_count': sold_count, 'sold_days': sold_days, 'label': label}

    social_tags_map = {}
    for m in re.finditer(
        r'tagg-txt[^>]*>\s*<strong>([^<]+)</strong>(.*?)</div>.*?aria-label="([^"]+)"',
        html_content, re.IGNORECASE | re.DOTALL
    ):
        tag_label = re.sub(r'<[^>]+>', ' ', m.group(1)).strip()
        pname = m.group(3).strip()
        if tag_label in ['Better Hurry', 'Selling Quickly']:
            continue
        if pname not in social_tags_map:
            social_tags_map[pname] = []
        social_tags_map[pname].append(tag_label)

    bestseller_set = set()
    for m in re.finditer(
        r'aria-label="([^"]+)".*?(?:Best\s*Seller|#\d+\s+Best\s*Seller|Top\s*Pick|Bestseller)',
        html_content, re.IGNORECASE | re.DOTALL
    ):
        bestseller_set.add(m.group(1).strip())
    if not bestseller_set:
        for m in re.finditer(
            r'(?:Best\s*Seller|#\d+\s+Best\s*Seller|Top\s*Pick|Bestseller)[^"]*?aria-label="([^"]+)"',
            html_content, re.IGNORECASE | re.DOTALL
        ):
            bestseller_set.add(m.group(1).strip())

    stock_map = {}
    for m in re.finditer(
        r'aria-label="([^"]+)".*?(\d+)\s+Left\s+in\s+Stock',
        html_content, re.IGNORECASE | re.DOTALL
    ):
        pname = m.group(1).strip()
        stock_count = int(m.group(2))
        stock_map[pname] = stock_count

    low_stock_set = set()
    for m in re.finditer(
        r'aria-label="([^"]+)".*?Low\s+Stock',
        html_content, re.IGNORECASE | re.DOTALL
    ):
        low_stock_set.add(m.group(1).strip())

    shipping_map = {}
    for m in re.finditer(
        r'aria-label="([^"]+)".*?FREE\s+(2-Day|3-Day|Fast\s+)?Delivery',
        html_content, re.IGNORECASE | re.DOTALL
    ):
        pname = m.group(1).strip()
        ship_type = m.group(2).strip() if m.group(2) else 'Standard'
        if pname not in shipping_map:
            shipping_map[pname] = ship_type

    sponsored_set = set()
    for m in re.finditer(
        r'aria-label="([^"]+)".*?isSponsored&quot;:true',
        html_content, re.IGNORECASE | re.DOTALL
    ):
        sponsored_set.add(m.group(1).strip())

    def _match_name(name, target_map):
        if not name:
            return None
        for tname in target_map:
            if tname in name or name in tname:
                return tname
        return None

    card_items = soup.select('[data-node-id*="ListingCollectionItem"]')
    if card_items:
        seen_urls = set()
        for page_rank, item in enumerate(card_items, 1):
            try:
                link = item.select_one('a[href*="/pdp/"]')
                url = link.get('href', '').split('?')[0] if link else ''

                if url in seen_urls:
                    continue
                seen_urls.add(url)

                name = ''
                image_url = ''
                imgs = item.find_all('img')
                for img in imgs:
                    alt = img.get('alt', '').strip()
                    if alt and len(alt) > 10:
                        lower = alt.lower()
                        if not any(kw in lower for kw in ['color', 'swatch', 'verified', 'deal', 'badge', 'icon', 'logo']):
                            name = alt
                            if not image_url:
                                image_url = _extract_img_url(img)
                            break

                if not image_url:
                    for img in imgs:
                        srcset = img.get('srcset', '')
                        if 'resize-h600' in srcset or 'resize-h400' in srcset:
                            image_url = _extract_img_url(img)
                            break

                if not name and url:
                    url_parts = url.split('/')
                    if len(url_parts) >= 6:
                        slug = url_parts[-1].replace('.html', '')
                        name = slug.replace('-', ' ').title()

                text = item.get_text(separator=' ', strip=True)

                price_match = re.search(r'\$([\d,]+\.?\d*)', text)
                price = float(price_match.group(1).replace(',', '')) if price_match else None

                was_match = re.search(r'was\s*\$([\d,]+\.?\d*)', text)
                was_price = float(was_match.group(1).replace(',', '')) if was_match else None

                rating_match = re.search(r'(\d+\.?\d*)\s*\([\d,]+', text)
                rating = float(rating_match.group(1)) if rating_match else None

                review_match = re.search(r'\(([\d,]+)\)', text)
                reviews = int(review_match.group(1).replace(',', '')) if review_match else None

                brand_match = re.search(r'By\s+([\w\s]+?)(?:\s*[\u2122\u00ae\u2117]|\s{2,}|$)', text)
                brand = brand_match.group(1).strip() if brand_match else ''

                sold_count = None
                sold_days = None
                sales_label = None
                if name:
                    matched = _match_name(name, hurry_map)
                    if matched:
                        sold_count = hurry_map[matched]['sold_count']
                        sold_days = hurry_map[matched]['sold_days']
                        sales_label = hurry_map[matched].get('label', 'Better Hurry')

                social_tags = []
                if name:
                    matched = _match_name(name, social_tags_map)
                    if matched:
                        social_tags = social_tags_map[matched]

                stock_left = None
                if name:
                    matched = _match_name(name, stock_map)
                    if matched:
                        stock_left = stock_map[matched]

                is_low_stock = False
                if name:
                    matched = _match_name(name, {s: s for s in low_stock_set})
                    if matched:
                        is_low_stock = True

                shipping_type = None
                if name:
                    matched = _match_name(name, shipping_map)
                    if matched:
                        shipping_type = shipping_map[matched]

                is_sponsored = False
                if name:
                    matched = _match_name(name, {s: s for s in sponsored_set})
                    if matched:
                        is_sponsored = True

                is_best_seller = False
                if name:
                    matched = _match_name(name, {s: s for s in bestseller_set})
                    if matched:
                        is_best_seller = True

                if name and price:
                    estimated_revenue = None
                    daily_sales_rate = None
                    if sold_count and sold_days and sold_days > 0:
                        estimated_revenue = round(price * sold_count, 2)
                        daily_sales_rate = round(sold_count / sold_days, 2)

                    products.append({
                        'name': name,
                        'price': price,
                        'original_price': was_price,
                        'rating': rating,
                        'review_count': reviews,
                        'brand': brand,
                        'url': url,
                        'image_url': image_url,
                        'sold_count': sold_count,
                        'sold_days': sold_days,
                        'sales_label': sales_label,
                        'social_tags': social_tags,
                        'stock_left': stock_left,
                        'is_low_stock': is_low_stock,
                        'shipping_type': shipping_type,
                        'is_sponsored': is_sponsored,
                        'is_best_seller': is_best_seller,
                        'page_rank': page_rank,
                        'estimated_revenue': estimated_revenue,
                        'daily_sales_rate': daily_sales_rate,
                        'category': page_category,
                        'breadcrumb': ' > '.join(page_breadcrumb) if page_breadcrumb else '',
                    })
            except Exception:
                continue

    if not products:
        banners = soup.select('[data-enzyme-id*="Product-Banner-Container"]')
        if banners:
            seen_urls = set()
            for page_rank, banner in enumerate(banners, 1):
                try:
                    name_el = banner.select_one('[data-enzyme-id*="ProductBannerName"]')
                    name = name_el.get_text(strip=True) if name_el else ''

                    pricing_el = banner.select_one('[data-enzyme-id*="ProductBannerPricingWrapper"]')
                    pricing_text = pricing_el.get_text(strip=True) if pricing_el else ''

                    price_match = re.search(r'\$([\d,]+\.?\d*)', pricing_text)
                    price = float(price_match.group(1).replace(',', '')) if price_match else None

                    was_match = re.search(r'was\s*\$([\d,]+\.?\d*)', pricing_text)
                    was_price = float(was_match.group(1).replace(',', '')) if was_match else None

                    review_el = banner.select_one('[data-enzyme-id*="reviewCount"]')
                    review_text = review_el.get_text(strip=True) if review_el else ''
                    review_match = re.search(r'([\d,]+)', review_text)
                    reviews = int(review_match.group(1).replace(',', '')) if review_match else None

                    rating_el = banner.select_one('[data-enzyme-id*="rating"]')
                    rating_text = rating_el.get_text(strip=True) if rating_el else ''
                    rating_match = re.search(r'(\d+\.?\d*)', rating_text)
                    rating = float(rating_match.group(1)) if rating_match else None

                    link_el = banner.find_parent('a') or banner.select_one('a[href]')
                    url = link_el.get('href', '').split('?')[0] if link_el else ''

                    if url in seen_urls:
                        continue
                    seen_urls.add(url)

                    sold_count = None
                    sold_days = None
                    sales_label = None
                    if name:
                        matched = _match_name(name, hurry_map)
                        if matched:
                            sold_count = hurry_map[matched]['sold_count']
                            sold_days = hurry_map[matched]['sold_days']
                            sales_label = hurry_map[matched].get('label', 'Better Hurry')

                    social_tags = []
                    if name:
                        matched = _match_name(name, social_tags_map)
                        if matched:
                            social_tags = social_tags_map[matched]

                    stock_left = None
                    if name:
                        matched = _match_name(name, stock_map)
                        if matched:
                            stock_left = stock_map[matched]

                    is_low_stock = False
                    if name:
                        matched = _match_name(name, {s: s for s in low_stock_set})
                        if matched:
                            is_low_stock = True

                    shipping_type = None
                    if name:
                        matched = _match_name(name, shipping_map)
                        if matched:
                            shipping_type = shipping_map[matched]

                    is_sponsored = False
                    if name:
                        matched = _match_name(name, {s: s for s in sponsored_set})
                        if matched:
                            is_sponsored = True

                    is_best_seller = False
                    if name:
                        matched = _match_name(name, {s: s for s in bestseller_set})
                        if matched:
                            is_best_seller = True

                    if name and price:
                        estimated_revenue = None
                        daily_sales_rate = None
                        if sold_count and sold_days and sold_days > 0:
                            estimated_revenue = round(price * sold_count, 2)
                            daily_sales_rate = round(sold_count / sold_days, 2)

                        products.append({
                            'name': name,
                            'price': price,
                            'original_price': was_price,
                            'rating': rating,
                            'review_count': reviews,
                            'brand': '',
                            'url': url,
                            'image_url': _extract_img_url_from_container(banner),
                            'sold_count': sold_count,
                            'sold_days': sold_days,
                            'sales_label': sales_label,
                            'social_tags': social_tags,
                            'stock_left': stock_left,
                            'is_low_stock': is_low_stock,
                            'shipping_type': shipping_type,
                            'is_sponsored': is_sponsored,
                            'is_best_seller': is_best_seller,
                            'page_rank': page_rank,
                            'estimated_revenue': estimated_revenue,
                            'daily_sales_rate': daily_sales_rate,
                            'category': page_category,
                            'breadcrumb': ' > '.join(page_breadcrumb) if page_breadcrumb else '',
                        })
                except Exception:
                    continue

    if not products:
        pdp_links = soup.find_all('a', href=re.compile(r'/pdp/'))
        if pdp_links:
            seen_urls = set()
            for page_rank, link_el in enumerate(pdp_links, 1):
                try:
                    url = link_el.get('href', '').split('?')[0]
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)

                    card = link_el
                    for _ in range(5):
                        if card.parent:
                            card = card.parent
                        else:
                            break

                    text = card.get_text(separator=' ', strip=True)

                    imgs = card.find_all('img')
                    name = ''
                    image_url = ''
                    for img in imgs:
                        alt = img.get('alt', '').strip()
                        if alt and len(alt) > 10:
                            lower = alt.lower()
                            if not any(kw in lower for kw in ['color', 'swatch', 'verified', 'deal', 'badge']):
                                name = alt
                                if not image_url:
                                    image_url = _extract_img_url(img)
                                break

                    if not image_url:
                        image_url = _extract_img_url_from_container(card)

                    if not name and url:
                        url_parts = url.split('/')
                        if len(url_parts) >= 6:
                            slug = url_parts[-1].replace('.html', '')
                            name = slug.replace('-', ' ').title()

                    price_match = re.search(r'\$([\d,]+\.?\d*)', text)
                    price = float(price_match.group(1).replace(',', '')) if price_match else None

                    was_match = re.search(r'was\s*\$([\d,]+\.?\d*)', text)
                    was_price = float(was_match.group(1).replace(',', '')) if was_match else None

                    rating_match = re.search(r'(\d+\.?\d*)\s*\([\d,]+', text)
                    rating = float(rating_match.group(1)) if rating_match else None

                    review_match = re.search(r'\(([\d,]+)\)', text)
                    reviews = int(review_match.group(1).replace(',', '')) if review_match else None

                    if name and price:
                        sold_count = None
                        sold_days = None
                        sales_label = None
                        if name:
                            matched = _match_name(name, hurry_map)
                            if matched:
                                sold_count = hurry_map[matched]['sold_count']
                                sold_days = hurry_map[matched]['sold_days']
                                sales_label = hurry_map[matched].get('label', 'Better Hurry')

                        social_tags = []
                        if name:
                            matched = _match_name(name, social_tags_map)
                            if matched:
                                social_tags = social_tags_map[matched]

                        stock_left = None
                        if name:
                            matched = _match_name(name, stock_map)
                            if matched:
                                stock_left = stock_map[matched]

                        is_low_stock = False
                        if name:
                            matched = _match_name(name, {s: s for s in low_stock_set})
                            if matched:
                                is_low_stock = True

                        shipping_type = None
                        if name:
                            matched = _match_name(name, shipping_map)
                            if matched:
                                shipping_type = shipping_map[matched]

                        is_sponsored = False
                        if name:
                            matched = _match_name(name, {s: s for s in sponsored_set})
                            if matched:
                                is_sponsored = True

                        is_best_seller = False
                        if name:
                            matched = _match_name(name, {s: s for s in bestseller_set})
                            if matched:
                                is_best_seller = True

                        estimated_revenue = None
                        daily_sales_rate = None
                        if sold_count and sold_days and sold_days > 0:
                            estimated_revenue = round(price * sold_count, 2)
                            daily_sales_rate = round(sold_count / sold_days, 2)

                        products.append({
                            'name': name,
                            'price': price,
                            'original_price': was_price,
                            'rating': rating,
                            'review_count': reviews,
                            'brand': '',
                            'url': url,
                            'image_url': image_url,
                            'sold_count': sold_count,
                            'sold_days': sold_days,
                            'sales_label': sales_label,
                            'social_tags': social_tags,
                            'stock_left': stock_left,
                            'is_low_stock': is_low_stock,
                            'shipping_type': shipping_type,
                            'is_sponsored': is_sponsored,
                            'is_best_seller': is_best_seller,
                            'page_rank': page_rank,
                            'estimated_revenue': estimated_revenue,
                            'daily_sales_rate': daily_sales_rate,
                            'category': page_category,
                            'breadcrumb': ' > '.join(page_breadcrumb) if page_breadcrumb else '',
                        })
                except Exception:
                    continue

    if not products:
        json_data = None
        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)
                if isinstance(data, list) and len(data) > 0:
                    for item in data:
                        if isinstance(item, dict) and item.get('@type') in ['Product', 'ItemList']:
                            json_data = data
                            break
                elif isinstance(data, dict) and data.get('@type') in ['Product', 'ItemList']:
                    json_data = data
                if json_data:
                    break
            except Exception:
                continue

        if json_data:
            items = []
            if isinstance(json_data, list):
                items = json_data
            elif isinstance(json_data, dict):
                if json_data.get('@type') == 'ItemList' and 'itemListElement' in json_data:
                    items = json_data['itemListElement']
                else:
                    items = [json_data]

            for page_rank, item in enumerate(items, 1):
                try:
                    if isinstance(item, dict):
                        product_name = item.get('name', '')
                        offers = item.get('offers', {})
                        if isinstance(offers, dict):
                            product_price = _parse_price_val(offers.get('price', ''))
                            product_orig = _parse_price_val(offers.get('highPrice', ''))
                        elif isinstance(offers, list) and len(offers) > 0:
                            product_price = _parse_price_val(offers[0].get('price', ''))
                            product_orig = None
                        else:
                            product_price = None
                            product_orig = None

                        agg = item.get('aggregateRating', {})
                        product_rating = float(agg.get('ratingValue', 0)) if isinstance(agg, dict) else None
                        product_reviews = int(agg.get('reviewCount', 0)) if isinstance(agg, dict) else None
                        product_url = item.get('url', '')
                        product_image = item.get('image', '')
                        if isinstance(product_image, list):
                            product_image = product_image[0] if product_image else ''
                        elif isinstance(product_image, dict):
                            product_image = product_image.get('url', '')

                        if product_name and product_price:
                            sold_count = None
                            sold_days = None
                            sales_label = None
                            matched = _match_name(product_name, hurry_map)
                            if matched:
                                sold_count = hurry_map[matched]['sold_count']
                                sold_days = hurry_map[matched]['sold_days']
                                sales_label = hurry_map[matched].get('label', 'Better Hurry')

                            social_tags = []
                            matched = _match_name(product_name, social_tags_map)
                            if matched:
                                social_tags = social_tags_map[matched]

                            stock_left = None
                            matched = _match_name(product_name, stock_map)
                            if matched:
                                stock_left = stock_map[matched]

                            is_low_stock = False
                            matched = _match_name(product_name, {s: s for s in low_stock_set})
                            if matched:
                                is_low_stock = True

                            shipping_type = None
                            matched = _match_name(product_name, shipping_map)
                            if matched:
                                shipping_type = shipping_map[matched]

                            is_sponsored = False
                            matched = _match_name(product_name, {s: s for s in sponsored_set})
                            if matched:
                                is_sponsored = True

                            is_best_seller = False
                            matched = _match_name(product_name, {s: s for s in bestseller_set})
                            if matched:
                                is_best_seller = True

                            estimated_revenue = None
                            daily_sales_rate = None
                            if sold_count and sold_days and sold_days > 0 and product_price:
                                estimated_revenue = round(product_price * sold_count, 2)
                                daily_sales_rate = round(sold_count / sold_days, 2)

                            products.append({
                                'name': product_name,
                                'price': product_price,
                                'original_price': product_orig,
                                'rating': product_rating,
                                'review_count': product_reviews,
                                'brand': '',
                                'url': product_url,
                                'image_url': product_image,
                                'sold_count': sold_count,
                                'sold_days': sold_days,
                                'sales_label': sales_label,
                                'social_tags': social_tags,
                                'stock_left': stock_left,
                                'is_low_stock': is_low_stock,
                                'shipping_type': shipping_type,
                                'is_sponsored': is_sponsored,
                                'is_best_seller': is_best_seller,
                                'page_rank': page_rank,
                                'estimated_revenue': estimated_revenue,
                                'daily_sales_rate': daily_sales_rate,
                                'category': page_category,
                                'breadcrumb': ' > '.join(page_breadcrumb) if page_breadcrumb else '',
                            })
                except Exception:
                    continue

    return products


def _parse_price_val(text):
    if not text:
        return None
    try:
        return float(str(text).replace(',', '').replace('$', ''))
    except Exception:
        return None


def _extract_img_url(img_tag):
    srcset = img_tag.get('srcset', '')
    if srcset:
        urls = re.findall(r'(https://assets\.wfcdn\.com/[^\s]+)', srcset)
        for u in urls:
            if 'resize-h600' in u or 'resize-h400' in u:
                return u.split(',')[0].strip() if ',' in u else u.strip()
        if urls:
            return urls[-1].strip()

    src = img_tag.get('src', '')
    if src and src.startswith('http'):
        return src

    return ''


def _extract_img_url_from_container(container):
    imgs = container.find_all('img')
    for img in imgs:
        srcset = img.get('srcset', '')
        if 'resize-h600' in srcset or 'resize-h400' in srcset:
            return _extract_img_url(img)

    for img in imgs:
        src = img.get('src', '')
        alt = img.get('alt', '')
        if src and alt and len(alt) > 10:
            return _extract_img_url(img)

    return ''


def extract_homedepot_html(html_content):
    products = []
    soup = BeautifulSoup(html_content, 'html.parser')

    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string)
            items = []

            if isinstance(data, list):
                for entry in data:
                    if isinstance(entry, dict):
                        if entry.get('@type') == 'WebPage':
                            me = entry.get('mainEntity', {})
                            offers = me.get('offers', {})
                            item_offered = offers.get('itemOffered', [])
                            if item_offered:
                                items = item_offered
                                break
                        elif entry.get('@type') == 'ItemList' and 'itemListElement' in entry:
                            items = entry['itemListElement']
                            break
                        elif entry.get('@type') == 'Product':
                            items.append(entry)
                if not items:
                    items = [e for e in data if isinstance(e, dict) and e.get('@type') == 'Product']
            elif isinstance(data, dict):
                if data.get('@type') == 'WebPage':
                    me = data.get('mainEntity', {})
                    offers = me.get('offers', {})
                    items = offers.get('itemOffered', [])
                elif data.get('@type') == 'ItemList' and 'itemListElement' in data:
                    items = data['itemListElement']
                elif data.get('@type') == 'Product':
                    items = [data]

            for item in items:
                try:
                    if not isinstance(item, dict) or item.get('@type') != 'Product':
                        continue

                    name = item.get('name', '')
                    if not name:
                        continue

                    offers = item.get('offers', {})
                    if isinstance(offers, dict):
                        price = _parse_price_val(offers.get('price', offers.get('lowPrice', '')))
                        original_price = _parse_price_val(offers.get('highPrice', ''))
                        url = offers.get('url', '')
                    elif isinstance(offers, list) and offers:
                        price = _parse_price_val(offers[0].get('price', ''))
                        original_price = None
                        url = offers[0].get('url', '')
                    else:
                        price = None
                        original_price = None
                        url = ''

                    if not price:
                        continue

                    agg = item.get('aggregateRating', {})
                    rating = None
                    reviews = None
                    if isinstance(agg, dict):
                        rv = agg.get('ratingValue')
                        if rv:
                            try:
                                rating = round(float(rv), 1)
                            except Exception:
                                pass
                        rc = agg.get('reviewCount')
                        if rc:
                            try:
                                reviews = int(rc)
                            except Exception:
                                pass

                    brand = item.get('brand', '')
                    if isinstance(brand, dict):
                        brand = brand.get('name', '')

                    image = item.get('image', '')
                    if isinstance(image, list):
                        image = image[0] if image else ''
                    elif isinstance(image, dict):
                        image = image.get('url', '')
                    if image and '_100.' in image:
                        image = image.replace('_100.', '_600.')

                    if name and price:
                        products.append({
                            'name': name,
                            'price': price,
                            'original_price': original_price,
                            'rating': rating,
                            'review_count': reviews,
                            'brand': brand,
                            'url': url,
                            'image_url': image,
                        })
                except Exception:
                    continue
        except Exception:
            continue

    if not products:
        json_data = None
        for script in soup.find_all('script', id='__NEXT_DATA__'):
            try:
                data = json.loads(script.string)
                json_data = data
                break
            except Exception:
                continue

        if json_data:
            try:
                props = json_data.get('props', {}).get('pageProps', {})
                search_results = props.get('searchState', {}).get('results', {})
                products_data = search_results.get('products', [])

                if not products_data:
                    products_data = props.get('dehydratedState', {}).get('queries', [])
                    for query in products_data:
                        state = query.get('state', {})
                        if 'products' in state:
                            products_data = state['products']
                            break
                        data_key = state.get('data', {})
                        if isinstance(data_key, dict) and 'products' in data_key:
                            products_data = data_key['products']
                            break

                if products_data:
                    seen_ids = set()
                    for p in products_data:
                        try:
                            product_id = p.get('itemId', '') or p.get('product', {}).get('itemId', '')
                            if product_id in seen_ids:
                                continue
                            seen_ids.add(product_id)

                            info = p.get('product', p) if isinstance(p, dict) else p

                            name = info.get('productLabel', '') or info.get('title', '') or info.get('name', '')
                            brand = info.get('brand', {}).get('name', '') if isinstance(info.get('brand'), dict) else info.get('brand', '')

                            price_info = info.get('pricing', info.get('price', {}))
                            if isinstance(price_info, dict):
                                price = _parse_price_val(price_info.get('value', price_info.get('original', '')))
                                original_price = _parse_price_val(price_info.get('original', ''))
                            else:
                                price = _parse_price_val(price_info)
                                original_price = None

                            rating = float(info.get('averageRating', 0)) if info.get('averageRating') else None
                            reviews = int(info.get('totalReviews', 0)) if info.get('totalReviews') else None

                            image_url = info.get('image', '')
                            if isinstance(image_url, dict):
                                image_url = image_url.get('url', '')
                            if not image_url:
                                images = info.get('mediaList', {}).get('images', [])
                                if images:
                                    image_url = images[0].get('url', '') or images[0].get('sizes', [{}])[-1].get('url', '')
                            if image_url and '_100.' in image_url:
                                image_url = image_url.replace('_100.', '_600.')

                            url = f"https://www.homedepot.com/p/{product_id}" if product_id else info.get('canonicalUrl', '')

                            if name and price:
                                products.append({
                                    'name': name,
                                    'price': price,
                                    'original_price': original_price,
                                    'rating': rating,
                                    'review_count': reviews,
                                    'brand': brand,
                                    'url': url,
                                    'image_url': image_url,
                                })
                        except Exception:
                            continue
            except Exception:
                pass

    if not products:
        product_cards = soup.select('[data-testid="product-card"]')
        if not product_cards:
            product_cards = soup.select('.product-pod')
        if not product_cards:
            product_cards = soup.select('[class*="ProductCard"]')

        seen_urls = set()
        for card in product_cards:
            try:
                link = card.select_one('a[href*="/p/"]')
                if not link:
                    link = card.find('a', href=True)
                url = link.get('href', '').split('?')[0] if link else ''
                if url in seen_urls or not url:
                    continue
                seen_urls.add(url)

                if not url.startswith('http'):
                    url = 'https://www.homedepot.com' + url

                name_el = card.select_one('[data-testid="product-card-title"]')
                if not name_el:
                    name_el = card.select_one('.product-pod--title')
                if not name_el:
                    name_el = card.select_one('h3, h4, [class*="title"], [class*="Title"]')
                name = name_el.get_text(strip=True) if name_el else ''

                if not name and link:
                    name = link.get_text(strip=True)

                price_el = card.select_one('[data-testid="product-card-price"]')
                if not price_el:
                    price_el = card.select_one('.price-format__main-price')
                if not price_el:
                    price_el = card.select_one('[class*="price"], [class*="Price"]')
                price_text = price_el.get_text(strip=True) if price_el else card.get_text(separator=' ', strip=True)
                price_match = re.search(r'\$([\d,]+\.?\d*)', price_text)
                price = float(price_match.group(1).replace(',', '')) if price_match else None

                rating_el = card.select_one('[class*="rating"], [class*="Rating"], [data-testid*="rating"]')
                rating_text = rating_el.get_text(strip=True) if rating_el else ''
                rating_match = re.search(r'(\d+\.?\d*)', rating_text)
                rating = float(rating_match.group(1)) if rating_match else None

                review_el = card.select_one('[class*="review"], [class*="Review"], [data-testid*="review"]')
                review_text = review_el.get_text(strip=True) if review_el else ''
                review_match = re.search(r'(\d[\d,]*)', review_text)
                reviews = int(review_match.group(1).replace(',', '')) if review_match else None

                image_url = ''
                img = card.select_one('img')
                if img:
                    image_url = img.get('src', '') or img.get('data-src', '')
                    srcset = img.get('srcset', '')
                    if srcset:
                        img_urls = re.findall(r'(https?://[^\s,]+)', srcset)
                        if img_urls:
                            image_url = img_urls[-1]
                    if image_url and '_100.' in image_url:
                        image_url = image_url.replace('_100.', '_600.')

                if name and price:
                    products.append({
                        'name': name,
                        'price': price,
                        'original_price': None,
                        'rating': rating,
                        'review_count': reviews,
                        'brand': '',
                        'url': url,
                        'image_url': image_url,
                    })
            except Exception:
                continue

    return products


with st.sidebar:
    st.header("🔧 控制面板")

    tab1, tab2, tab3, tab4 = st.tabs(["🌐 网页提取", "🏠 Home Depot", "🤖 辅助抓取", "📂 手动导入"])

    with tab1:
        st.subheader("从 Wayfair 网页提取数据")
        st.markdown("**最可靠的方式! 无需任何自动化,不会被拦截**")

        with st.expander("📖 操作步骤 (点击展开)", expanded=True):
            st.markdown("""
            **第一步: 打开 Wayfair**
            1. 用 Edge 浏览器打开 [wayfair.com](https://www.wayfair.com)
            2. 如果有代理,请先配置好代理再打开

            **第二步: 搜索产品**
            3. 在 Wayfair 搜索框输入关键词 (如: sofa)
            4. 如果出现验证,手动完成即可

            **第三步: 保存网页**
            5. 按 **Ctrl + S** 保存网页
            6. 保存类型选择 **"网页,全部"** 或 **"Webpage, Complete"**
            7. 保存到任意位置

            **第四步: 上传提取**
            8. 在下方上传保存的 HTML 文件
            9. 系统自动提取产品数据!
            """)

        html_file = st.file_uploader("📤 上传 Wayfair 搜索结果页面", type=['html', 'htm'], key="html_upload")

        if html_file is not None:
            try:
                html_content = html_file.read().decode('utf-8', errors='ignore')
                with st.spinner("正在提取产品数据..."):
                    products = extract_wayfair_html(html_content)

                if products:
                    new_df = pd.DataFrame(products)
                    if st.session_state.products_data is not None:
                        existing = st.session_state.products_data
                        combined = pd.concat([existing, new_df], ignore_index=True)
                        combined = combined.drop_duplicates(subset=['name'], keep='last')
                        st.session_state.products_data = combined
                    else:
                        st.session_state.products_data = new_df
                    st.success(f"✅ 提取到 {len(products)} 个产品! (共 {len(st.session_state.products_data)} 个)")
                    with st.expander("预览数据"):
                        st.dataframe(new_df.head(10), use_container_width=True)
                else:
                    st.warning("未提取到产品数据")
                    st.info("请确保上传的是 Wayfair 搜索结果页面 (不是首页或验证页)")
            except Exception as e:
                st.error(f"提取失败: {e}")

        st.markdown("---")
        st.markdown("💡 可以多次上传不同页面的 HTML,数据会自动合并")

    with tab2:
        st.subheader("从 Home Depot 网页提取数据")
        st.markdown("**支持 Home Depot 搜索结果页面提取**")

        with st.expander("📖 操作步骤 (点击展开)", expanded=True):
            st.markdown("""
            **第一步: 打开 Home Depot**
            1. 用浏览器打开 [homedepot.com](https://www.homedepot.com)
            2. 如果有代理,请先配置好代理再打开

            **第二步: 搜索产品**
            3. 在 Home Depot 搜索框输入关键词 (如: outdoor sofa)
            4. 等待搜索结果完全加载

            **第三步: 保存网页**
            5. 按 **Ctrl + S** 保存网页
            6. 保存类型选择 **"网页,全部"** 或 **"Webpage, Complete"**
            7. 保存到任意位置

            **第四步: 上传提取**
            8. 在下方上传保存的 HTML 文件
            9. 系统自动提取产品数据!
            """)

        hd_file = st.file_uploader("📤 上传 Home Depot 搜索结果页面", type=['html', 'htm'], key="hd_upload")

        if hd_file is not None:
            try:
                hd_content = hd_file.read().decode('utf-8', errors='ignore')
                with st.spinner("正在提取 Home Depot 产品数据..."):
                    products = extract_homedepot_html(hd_content)

                if products:
                    new_df = pd.DataFrame(products)
                    if st.session_state.products_data is not None:
                        existing = st.session_state.products_data
                        combined = pd.concat([existing, new_df], ignore_index=True)
                        combined = combined.drop_duplicates(subset=['name'], keep='last')
                        st.session_state.products_data = combined
                    else:
                        st.session_state.products_data = new_df
                    st.success(f"✅ 提取到 {len(products)} 个产品! (共 {len(st.session_state.products_data)} 个)")
                    with st.expander("预览数据"):
                        st.dataframe(new_df.head(10), use_container_width=True)
                else:
                    st.warning("未提取到产品数据")
                    st.info("请确保上传的是 Home Depot 搜索结果页面 (不是首页或验证页)")
            except Exception as e:
                st.error(f"提取失败: {e}")

        st.markdown("---")
        st.markdown("💡 Wayfair 和 Home Depot 的数据可以合并分析,也可以单独查看")

    with tab3:
        st.subheader("辅助抓取 Wayfair 数据")

        if not SCRAPER_AVAILABLE:
            st.warning("⚠️ 辅助抓取功能暂不可用")
            st.info("请使用「🌐 网页提取」标签,更简单可靠!")
        else:
            st.info("1. 点击「打开浏览器」启动 Edge\n2. 在浏览器中手动搜索 Wayfair 产品\n3. 搜索结果加载后点击「提取当前页面」")

            proxy_enabled = st.checkbox("🌐 使用代理", value=False, help="通过代理访问 Wayfair (推荐海外代理)", key="proxy2")
            proxy_url = None
            if proxy_enabled:
                proxy_url = st.text_input(
                    "代理地址",
                    placeholder="socks5://127.0.0.1:1080 或 http://user:pass@ip:port",
                    help="SOCKS5/HTTP 代理地址",
                    key="proxy_url2"
                )

            col1, col2 = st.columns(2)

            with col1:
                if st.button("🌐 打开浏览器", use_container_width=True, key="btn_open"):
                    try:
                        scraper = WayfairScraper(headless=False, proxy=proxy_url if proxy_enabled else None)
                        if scraper.init_driver():
                            st.session_state.scraper = scraper
                            st.success("✅ 浏览器已打开! 请在浏览器中搜索产品")
                        else:
                            st.error("浏览器启动失败")
                    except Exception as e:
                        st.error(f"启动失败: {e}")

            with col2:
                if st.button("📋 提取当前页面", type="primary", use_container_width=True, key="btn_extract"):
                    scraper = st.session_state.get('scraper')
                    if scraper and scraper.driver:
                        with st.spinner("正在提取当前页面数据..."):
                            try:
                                products = scraper.extract_current_page()
                                if products:
                                    if st.session_state.products_data is not None:
                                        existing = st.session_state.products_data
                                        new_df = pd.DataFrame(products)
                                        st.session_state.products_data = pd.concat([existing, new_df], ignore_index=True)
                                    else:
                                        st.session_state.products_data = pd.DataFrame(products)
                                    st.success(f"✅ 提取到 {len(products)} 个产品! (共 {len(st.session_state.products_data)} 个)")
                                else:
                                    st.warning("未提取到数据,请确保浏览器显示的是搜索结果页")
                            except Exception as e:
                                st.error(f"提取失败: {e}")
                    else:
                        st.warning("请先点击「打开浏览器」")

            if st.session_state.get('scraper') and hasattr(st.session_state.scraper, 'driver') and st.session_state.scraper.driver:
                if st.button("🔒 关闭浏览器", use_container_width=True, key="btn_close"):
                    try:
                        st.session_state.scraper.close()
                        st.session_state.scraper = None
                        st.success("浏览器已关闭")
                    except Exception:
                        st.session_state.scraper = None

    with tab4:
        st.subheader("手动导入数据文件")

        st.markdown("""
        **数据格式要求:**
        - name (必填): 产品名称
        - price (必填): 价格
        - original_price (选填): 原价
        - rating (选填): 评分
        - review_count (选填): 评论数
        """)

        uploaded_file = st.file_uploader("上传 Excel/CSV 文件", type=['xlsx', 'csv'], key="file_upload")

        if uploaded_file is not None:
            try:
                if uploaded_file.name.endswith('.csv'):
                    df = pd.read_csv(uploaded_file)
                else:
                    df = pd.read_excel(uploaded_file)

                required_cols = ['name', 'price']
                missing_cols = [col for col in required_cols if col not in df.columns]

                if missing_cols:
                    st.error(f"缺少必要列: {', '.join(missing_cols)}")
                else:
                    st.session_state.products_data = df
                    st.success(f"成功导入 {len(df)} 条数据!")
                    st.dataframe(df.head(10), use_container_width=True)
            except Exception as e:
                st.error(f"导入失败: {e}")

    st.divider()

    st.subheader("📊 分析设置")

    with st.expander("⚖️ 评分权重调整", expanded=False):
        st.markdown("**拖动滑块调整各维度的重要性,权重会自动归一化**")

        if 'custom_weights' not in st.session_state:
            st.session_state.custom_weights = ProductScorer.DEFAULT_WEIGHTS.copy()

        preset = st.selectbox(
            "快速预设",
            ["自定义", "均衡模式", "价格优先", "需求优先", "评分优先", "紧迫性优先"],
            index=0,
            help="选择预设权重方案,或自定义调整"
        )

        presets = {
            "均衡模式": {
                'price_score': 0.17, 'demand_score': 0.17,
                'rating_score': 0.17, 'review_score': 0.17,
                'discount_score': 0.16, 'sales_urgency_score': 0.16,
            },
            "价格优先": {
                'price_score': 0.35, 'demand_score': 0.10,
                'rating_score': 0.10, 'review_score': 0.10,
                'discount_score': 0.20, 'sales_urgency_score': 0.15,
            },
            "需求优先": {
                'price_score': 0.10, 'demand_score': 0.35,
                'rating_score': 0.10, 'review_score': 0.20,
                'discount_score': 0.05, 'sales_urgency_score': 0.20,
            },
            "评分优先": {
                'price_score': 0.10, 'demand_score': 0.15,
                'rating_score': 0.35, 'review_score': 0.15,
                'discount_score': 0.05, 'sales_urgency_score': 0.20,
            },
            "紧迫性优先": {
                'price_score': 0.10, 'demand_score': 0.15,
                'rating_score': 0.10, 'review_score': 0.10,
                'discount_score': 0.10, 'sales_urgency_score': 0.45,
            },
        }

        if preset != "自定义" and preset in presets:
            st.session_state.custom_weights = presets[preset].copy()

        new_weights = {}
        for key in ProductScorer.DEFAULT_WEIGHTS:
            label = ProductScorer.WEIGHT_LABELS.get(key, key)
            desc = ProductScorer.WEIGHT_DESCRIPTIONS.get(key, '')
            current_val = st.session_state.custom_weights.get(key, ProductScorer.DEFAULT_WEIGHTS[key])
            val = st.slider(
                f"{label}",
                min_value=0, max_value=100,
                value=int(current_val * 100),
                help=desc,
                key=f"w2_{key}"
            )
            new_weights[key] = val / 100.0

        st.session_state.custom_weights = new_weights

        total_weight = sum(new_weights.values())
        st.markdown(f"**权重总计: {total_weight:.0%}** (系统会自动归一化)")

        weight_cols = st.columns(3)
        weight_items = list(new_weights.items())
        for i, (key, val) in enumerate(weight_items):
            label = ProductScorer.WEIGHT_LABELS.get(key, key)
            normalized = val / total_weight if total_weight > 0 else 0
            with weight_cols[i % 3]:
                st.markdown(f"**{label}**: {normalized:.1%}")

    if st.button("🔍 开始分析", type="primary", use_container_width=True):
        if st.session_state.products_data is not None:
            with st.spinner("正在分析产品数据..."):
                scorer = ProductScorer(weights=st.session_state.custom_weights)
                analyzed = scorer.calculate_all_scores(st.session_state.products_data)
                extractor = KeywordExtractor()
                analyzed, seg_stats = extractor.analyze_dataframe(analyzed)
                st.session_state.analyzed_data = analyzed
                st.session_state.segment_stats = seg_stats
                st.success("分析完成!")
        else:
            st.warning("请先抓取或导入数据")

    st.divider()

    st.subheader("📈 筛选条件")

    if st.session_state.analyzed_data is not None:
        min_score = st.slider("最低评分", min_value=0, max_value=100, value=0)

        price_range = st.slider("价格区间 ($)",
                               min_value=0,
                               max_value=int(st.session_state.analyzed_data['price'].max()),
                               value=(0, int(st.session_state.analyzed_data['price'].max())))

        recommendation_filter = st.multiselect(
            "推荐等级",
            options=['强烈推荐', '推荐', '可以考虑', '谨慎考虑', '不推荐'],
            default=['强烈推荐', '推荐', '可以考虑']
        )


if st.session_state.analyzed_data is not None:
    df_full = st.session_state.analyzed_data.copy()
    df = df_full.copy()

    if 'min_score' in locals():
        df = df[df['total_score'] >= min_score]

    if 'price_range' in locals():
        df = df[(df['price'] >= price_range[0]) & (df['price'] <= price_range[1])]

    if 'recommendation_filter' in locals() and len(recommendation_filter) > 0:
        df = df[df['recommendation'].isin(recommendation_filter)]

    if len(df) != len(df_full):
        st.info(f"📊 共导入 **{len(df_full)}** 个产品，当前筛选显示 **{len(df)}** 个")

    st.subheader("📊 数据概览")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("产品总数", len(df))

    with col2:
        avg_price = df['price'].mean() if 'price' in df.columns else 0
        st.metric("平均价格", f"${avg_price:.2f}")

    with col3:
        avg_rating = df['rating'].mean() if 'rating' in df.columns else 0
        st.metric("平均评分", f"{avg_rating:.2f}")

    with col4:
        highly_recommended = len(df[df['recommendation'] == '强烈推荐'])
        st.metric("强烈推荐", highly_recommended)

    st.markdown("---")

    st.subheader("📈 可视化分析")

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["价格分布", "评分分析", "选品指标雷达图", "关键词分析", "推荐产品列表"])

    with tab1:
        if 'price' in df.columns:
            fig = px.histogram(
                df,
                x='price',
                nbins=20,
                title="产品价格分布",
                labels={'price': '价格 ($)', 'count': '产品数量'}
            )
            fig.update_layout(showlegend=False)
            st.plotly_chart(fig, use_container_width=True)

    with tab2:
        if 'rating' in df.columns:
            col1, col2 = st.columns(2)

            with col1:
                fig = px.histogram(
                    df,
                    x='rating',
                    nbins=10,
                    title="产品评分分布",
                    labels={'rating': '评分', 'count': '产品数量'}
                )
                fig.update_layout(showlegend=False)
                st.plotly_chart(fig, use_container_width=True)

            with col2:
                if 'recommendation' in df.columns:
                    rec_counts = df['recommendation'].value_counts()
                    fig = px.pie(
                        values=rec_counts.values,
                        names=rec_counts.index,
                        title="推荐等级分布"
                    )
                    st.plotly_chart(fig, use_container_width=True)

    with tab3:
        if len(df) > 0:
            metrics_to_show = ['price_score', 'demand_score', 'rating_score',
                             'review_score', 'discount_score', 'sales_urgency_score']
            metric_labels = {
                'price_score': '价格优势',
                'demand_score': '需求热度',
                'rating_score': '评分表现',
                'review_score': '评论趋势',
                'discount_score': '折扣力度',
                'sales_urgency_score': '销售紧迫',
            }
            available_metrics = [m for m in metrics_to_show if m in df.columns]

            if available_metrics:
                sub_tab1, sub_tab2 = st.tabs(["🔍 对比雷达图", "📊 评分热力图"])

                with sub_tab1:
                    product_names = df['name'].apply(lambda x: str(x)[:40]).tolist()
                    top_5_names = df.nlargest(5, 'total_score')['name'].apply(lambda x: str(x)[:40]).tolist()

                    selected_names = st.multiselect(
                        "选择要对比的产品（建议2-3个）",
                        options=product_names,
                        default=top_5_names[:3],
                        max_selections=4,
                        key="radar_select"
                    )

                    if selected_names:
                        selected_df = df[df['name'].apply(lambda x: str(x)[:40]).isin(selected_names)]
                        fig = go.Figure()
                        colors = ['#636EFA', '#EF553B', '#00CC96', '#AB63FA']
                        for i, (idx, row) in enumerate(selected_df.iterrows()):
                            fig.add_trace(go.Scatterpolar(
                                r=[row[m] for m in available_metrics],
                                theta=[metric_labels.get(m, m.replace('_score', '')) for m in available_metrics],
                                fill='toself',
                                opacity=0.25,
                                name=str(row.get('name', ''))[:30],
                                line=dict(color=colors[i % len(colors)], width=2),
                            ))
                        fig.update_layout(
                            polar=dict(radialaxis=dict(visible=True, range=[0, 100], tickvals=[20, 40, 60, 80, 100])),
                            showlegend=True,
                            height=500,
                        )
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.info("请选择至少1个产品进行对比")

                with sub_tab2:
                    heatmap_df = df.nlargest(15, 'total_score')
                    display_labels = [metric_labels.get(m, m) for m in available_metrics]
                    product_short = heatmap_df['name'].apply(lambda x: str(x)[:25])

                    z_data = []
                    for m in available_metrics:
                        z_data.append(heatmap_df[m].tolist())

                    fig = go.Figure(data=go.Heatmap(
                        z=z_data,
                        x=product_short.tolist(),
                        y=display_labels,
                        colorscale=[
                            [0, '#FF6B6B'],
                            [0.5, '#FFE66D'],
                            [1, '#4ECB71']
                        ],
                        text=[[f"{v:.0f}" for v in row] for row in z_data],
                        texttemplate="%{text}",
                        textfont={"size": 11},
                        hovertemplate="%{y}<br>%{x}<br>得分: %{text}<extra></extra>",
                    ))
                    fig.update_layout(
                        height=max(350, len(available_metrics) * 45 + 100),
                        xaxis_tickangle=-30,
                        yaxis=dict(tickfont=dict(size=12)),
                    )
                    st.plotly_chart(fig, use_container_width=True)

    with tab4:
        if 'segments' in df.columns and st.session_state.get('segment_stats'):
            seg_stats = st.session_state.segment_stats
            extractor = KeywordExtractor()

            seg_sub1, seg_sub2, seg_sub3 = st.tabs(["🏷️ 筛选词段分布", "📊 词段维度数据", "🔍 按词段筛选产品"])

            cat_labels_cn = {
                'piece': '件数', 'person': '人数', 'product_type': '产品类型',
                'location': '位置', 'material': '材质', 'color': '颜色',
                'style': '风格', 'feature': '特征',
            }
            cat_colors = {
                '件数': '#636EFA', '人数': '#AB63FA', '产品类型': '#EF553B',
                '位置': '#00CC96', '材质': '#FFA15A', '颜色': '#19D3F3',
                '风格': '#FF6692', '特征': '#B6E880',
            }

            with seg_sub1:
                all_seg_data = []
                for cat, segs in seg_stats.items():
                    for text, count in segs.items():
                        all_seg_data.append({
                            '类别': cat_labels_cn.get(cat, cat),
                            '词段': text,
                            '数量': count,
                        })
                if all_seg_data:
                    seg_df = pd.DataFrame(all_seg_data)
                    seg_df = seg_df.sort_values('数量', ascending=False)

                    st.markdown("#### 各类别筛选词段分布")
                    cat_options = ['全部'] + list(seg_df['类别'].unique())
                    selected_cat = st.selectbox("选择类别筛选", cat_options, key="seg_cat_filter")
                    if selected_cat != '全部':
                        display_df = seg_df[seg_df['类别'] == selected_cat]
                    else:
                        display_df = seg_df

                    fig = px.bar(
                        display_df.head(30),
                        x='数量', y='词段',
                        color='类别',
                        orientation='h',
                        title="筛选词段频次排行 (TOP 30)",
                        color_discrete_map=cat_colors,
                    )
                    fig.update_layout(yaxis={'categoryorder': 'total ascending'}, height=max(500, len(display_df.head(30)) * 28))
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("未提取到筛选词段")

            with seg_sub2:
                seg_analytics = extractor.get_segment_analytics(df)
                if not seg_analytics.empty:
                    seg_analytics['类别'] = seg_analytics['category'].map(cat_labels_cn).fillna(seg_analytics['category'])

                    st.markdown("#### 筛选词段维度数据表")
                    display_cols = ['segment', '类别', 'count', 'avg_price', 'avg_score', 'avg_rating']
                    display_labels = {'segment': '词段', '类别': '类别', 'count': '产品数', 'avg_price': '均价($)', 'avg_score': '均分', 'avg_rating': '均评分'}
                    show_df = seg_analytics[display_cols].rename(columns=display_labels)
                    st.dataframe(show_df, use_container_width=True, hide_index=True)

                    st.markdown("#### 词段维度对比图")
                    dim_cat = st.selectbox(
                        "选择维度对比",
                        ['均价($)', '均分', '均评分', '产品数'],
                        key="seg_dim_select"
                    )
                    dim_cat_map = {'均价($)': 'avg_price', '均分': 'avg_score', '均评分': 'avg_rating', '产品数': 'count'}
                    sort_col = dim_cat_map[dim_cat]
                    chart_df = seg_analytics.copy()
                    chart_df['显示名'] = chart_df['segment'] + ' (' + chart_df['类别'] + ')'
                    top_n = st.slider("显示数量", 5, 30, 15, key="seg_topn")
                    chart_df = chart_df.head(top_n).sort_values(sort_col, ascending=True)
                    fig = px.bar(
                        chart_df,
                        x=sort_col, y='显示名',
                        color='类别',
                        orientation='h',
                        title=f"筛选词段 {dim_cat} 对比 (TOP {top_n})",
                        color_discrete_map=cat_colors,
                    )
                    fig.update_layout(height=max(400, len(chart_df) * 28), yaxis=dict(tickfont=dict(size=12)))
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("需要评分数据才能展示维度分析")

            with seg_sub3:
                st.markdown("#### 按筛选词段筛选产品")
                all_segments_list = []
                for cat, segs in seg_stats.items():
                    for text, count in segs.items():
                        all_segments_list.append(f"{text} ({cat_labels_cn.get(cat, cat)}) [{count}个产品]")

                selected_segs = st.multiselect(
                    "选择筛选词段查看对应产品",
                    all_segments_list,
                    max_selections=5,
                    key="seg_product_filter"
                )

                if selected_segs:
                    for sel in selected_segs:
                        seg_text = sel.split(' (')[0]
                        matching = df[df['segments'].apply(lambda s: any(seg['text'] == seg_text for seg in s))]
                        st.markdown(f"**{seg_text}** — {len(matching)} 个产品")
                        if not matching.empty:
                            show_cols = ['name', 'price']
                            if 'total_score' in matching.columns:
                                show_cols.append('total_score')
                            if 'rating' in matching.columns:
                                show_cols.append('rating')
                            if 'recommendation' in matching.columns:
                                show_cols.append('recommendation')
                            available_cols = [c for c in show_cols if c in matching.columns]
                            st.dataframe(matching[available_cols].head(20), use_container_width=True, hide_index=True)
                        st.divider()
                else:
                    st.info("请选择筛选词段来查看对应产品")
        else:
            st.info("请先点击「开始分析」以提取筛选词段数据")

    with tab5:
        st.subheader("🏆 推荐产品列表")

        if 'recommendation' in df.columns:
            recommendation_order = ['强烈推荐', '推荐', '可以考虑', '谨慎考虑', '不推荐']
            df['recommendation'] = pd.Categorical(df['recommendation'], categories=recommendation_order, ordered=True)
            df = df.sort_values('recommendation', ascending=True)

        if 'image_url' in df.columns and df['image_url'].notna().any():
            has_images = True
            display_df = df[df['image_url'].notna() & (df['image_url'] != '')].head(20)
        else:
            has_images = False
            display_df = df.head(20)

        if has_images and len(display_df) > 0:
            st.markdown("### 🖼️ 产品图片速览")
            cols_per_row = 4
            for start in range(0, len(display_df), cols_per_row):
                row_data = display_df.iloc[start:start + cols_per_row]
                cols = st.columns(cols_per_row)
                for i, (idx, row) in enumerate(row_data.iterrows()):
                    with cols[i]:
                        img_url = row.get('image_url', '')
                        if img_url and isinstance(img_url, str) and img_url.startswith('http'):
                            display_url = re.sub(r'resize-h\d+-w\d+', 'resize-h300-w300', img_url)
                            st.image(display_url, use_container_width=True)
                        else:
                            st.markdown("🖼️ *无图片*")

                        name = str(row.get('name', ''))[:40]
                        price = row.get('price', 0)
                        rating = row.get('rating', '-')
                        score = row.get('total_score', 0)
                        rec = row.get('recommendation', '')

                        rec_emoji = {'强烈推荐': '🔥', '推荐': '👍', '可以考虑': '🤔', '谨慎考虑': '⚠️', '不推荐': '❌'}.get(str(rec), '')

                        price_str = f"${price:.2f}" if pd.notna(price) else '-'
                        rating_str = f"{rating}" if pd.notna(rating) and rating != '-' else '-'
                        score_str = f"{score:.1f}" if pd.notna(score) else '-'

                        st.markdown(f"**{name}**")
                        category = row.get('category')
                        if pd.notna(category) and category:
                            st.markdown(f"📂 {category}")
                        st.markdown(f"{price_str} | ⭐{rating_str} | {rec_emoji}{rec}")
                        st.markdown(f"综合评分: **{score_str}**")

                        sold_count = row.get('sold_count')
                        sold_days = row.get('sold_days')
                        sales_label = row.get('sales_label')
                        if pd.notna(sold_count) and sold_count:
                            days_str = int(sold_days) if pd.notna(sold_days) else '?'
                            label_text = sales_label if pd.notna(sales_label) and sales_label else 'Better Hurry'
                            st.markdown(f"🔥 **{label_text}**: {int(sold_count)} sold in {days_str} days")

                        social_tags = row.get('social_tags')
                        if social_tags and isinstance(social_tags, (list, str)):
                            if isinstance(social_tags, str):
                                try:
                                    import json
                                    social_tags = json.loads(social_tags)
                                except Exception:
                                    social_tags = [social_tags]
                            if social_tags:
                                tags_str = ' | '.join([f'🏷️ {t}' for t in social_tags])
                                st.markdown(tags_str)

                        stock_left = row.get('stock_left')
                        if pd.notna(stock_left) and stock_left:
                            st.markdown(f"📦 **库存**: {int(stock_left)} left")

                        is_low_stock = row.get('is_low_stock')
                        if is_low_stock is True:
                            st.markdown(f"⚠️ **低库存**")

                        shipping_type = row.get('shipping_type')
                        if shipping_type and pd.notna(shipping_type):
                            st.markdown(f"🚚 **配送**: FREE {shipping_type} Delivery")

                        is_sponsored = row.get('is_sponsored')
                        if is_sponsored is True:
                            st.markdown(f"📢 **广告产品**")

                        is_best_seller = row.get('is_best_seller')
                        if is_best_seller is True:
                            st.markdown(f"🏆 **Best Seller**")

                        page_rank = row.get('page_rank')
                        if pd.notna(page_rank) and page_rank:
                            st.markdown(f"📊 **搜索排名**: #{int(page_rank)}")

                        estimated_revenue = row.get('estimated_revenue')
                        if pd.notna(estimated_revenue) and estimated_revenue:
                            st.markdown(f"💰 **估算销售额**: ${estimated_revenue:,.0f}")

                        daily_sales_rate = row.get('daily_sales_rate')
                        if pd.notna(daily_sales_rate) and daily_sales_rate:
                            st.markdown(f"📈 **日均销量**: {daily_sales_rate:.1f}/day")

                        url = row.get('url', '')
                        if url and isinstance(url, str) and url.startswith('http'):
                            st.markdown(f"[查看详情 ↗]({url})")

            st.markdown("---")

        display_cols = ['name', 'category', 'breadcrumb', 'price', 'rating', 'review_count', 'sold_count', 'sold_days', 'sales_label', 'social_tags', 'stock_left', 'is_low_stock', 'shipping_type', 'is_sponsored', 'is_best_seller', 'page_rank', 'estimated_revenue', 'daily_sales_rate', 'total_score', 'recommendation']
        available_cols = [c for c in display_cols if c in df.columns]

        df_display = df[available_cols].copy()

        if 'name' in df_display.columns:
            df_display['name'] = df_display['name'].apply(lambda x: str(x)[:50] + '...' if len(str(x)) > 50 else x)

        if 'price' in df_display.columns:
            df_display['price'] = df_display['price'].apply(lambda x: f"${x:.2f}" if pd.notna(x) else '-')

        if 'sold_count' in df_display.columns:
            df_display['sold_count'] = df_display['sold_count'].apply(lambda x: int(x) if pd.notna(x) else '-')

        if 'sold_days' in df_display.columns:
            df_display['sold_days'] = df_display['sold_days'].apply(lambda x: int(x) if pd.notna(x) else '-')

        if 'stock_left' in df_display.columns:
            df_display['stock_left'] = df_display['stock_left'].apply(lambda x: int(x) if pd.notna(x) else '-')

        if 'is_low_stock' in df_display.columns:
            df_display['is_low_stock'] = df_display['is_low_stock'].apply(lambda x: '⚠️' if x is True else '')

        if 'is_sponsored' in df_display.columns:
            df_display['is_sponsored'] = df_display['is_sponsored'].apply(lambda x: '📢' if x is True else '')

        if 'is_best_seller' in df_display.columns:
            df_display['is_best_seller'] = df_display['is_best_seller'].apply(lambda x: '🏆' if x is True else '')

        if 'estimated_revenue' in df_display.columns:
            df_display['estimated_revenue'] = df_display['estimated_revenue'].apply(lambda x: f"${x:,.0f}" if pd.notna(x) else '-')

        if 'daily_sales_rate' in df_display.columns:
            df_display['daily_sales_rate'] = df_display['daily_sales_rate'].apply(lambda x: f"{x:.1f}/day" if pd.notna(x) else '-')

        if 'page_rank' in df_display.columns:
            df_display['page_rank'] = df_display['page_rank'].apply(lambda x: f"#{int(x)}" if pd.notna(x) else '-')

        if 'shipping_type' in df_display.columns:
            df_display['shipping_type'] = df_display['shipping_type'].apply(lambda x: str(x) if pd.notna(x) and x else '')

        if 'rating' in df_display.columns:
            df_display['rating'] = df_display['rating'].apply(lambda x: f"{x:.1f}" if pd.notna(x) else '-')

        if 'review_count' in df_display.columns:
            df_display['review_count'] = df_display['review_count'].apply(lambda x: int(x) if pd.notna(x) else '-')

        if 'social_tags' in df_display.columns:
            df_display['social_tags'] = df_display['social_tags'].apply(
                lambda x: ', '.join(x) if isinstance(x, list) and len(x) > 0 else ''
            )

        if 'sales_label' in df_display.columns:
            df_display['sales_label'] = df_display['sales_label'].apply(
                lambda x: str(x) if pd.notna(x) and x else ''
            )

        if 'total_score' in df_display.columns:
            df_display['total_score'] = df_display['total_score'].apply(lambda x: f"{x:.1f}" if pd.notna(x) else '-')

        st.dataframe(df_display, use_container_width=True, height=400)

    st.markdown("---")

    st.subheader("📋 详细分析报告")

    with st.expander("📊 市场概览", expanded=True):
        overview_cols = st.columns(4)
        with overview_cols[0]:
            if len(df) != len(df_full):
                st.metric("产品总数", f"{len(df)} / {len(df_full)}", delta="筛选后 / 全部")
            else:
                st.metric("产品总数", len(df))
            if 'price' in df.columns:
                valid_prices = df['price'].dropna()
                if len(valid_prices) > 0:
                    st.metric("价格区间", f"${valid_prices.min():.0f} ~ ${valid_prices.max():.0f}")
                    st.metric("平均价格", f"${valid_prices.mean():.2f}")
        with overview_cols[1]:
            if 'rating' in df.columns:
                valid_ratings = df['rating'].dropna()
                if len(valid_ratings) > 0:
                    st.metric("平均评分", f"{valid_ratings.mean():.2f}")
                    st.metric("4.5分以上", f"{len(valid_ratings[valid_ratings >= 4.5])} 个")
                    st.metric("4.0-4.5分", f"{len(valid_ratings[(valid_ratings >= 4.0) & (valid_ratings < 4.5)])} 个")
        with overview_cols[2]:
            if 'review_count' in df.columns:
                valid_reviews = df['review_count'].dropna()
                if len(valid_reviews) > 0:
                    st.metric("平均评论数", f"{valid_reviews.mean():.0f}")
                    st.metric("100以下", f"{len(valid_reviews[valid_reviews < 100])} 个")
                    st.metric("500以上", f"{len(valid_reviews[valid_reviews >= 500])} 个")
        with overview_cols[3]:
            if 'recommendation' in df.columns:
                rec_counts = df['recommendation'].value_counts()
                for rec in ['强烈推荐', '推荐', '可以考虑']:
                    count = rec_counts.get(rec, 0)
                    st.metric(rec, f"{count} 个")

    with st.expander("💰 销售数据分析", expanded=True):
        has_sales = 'sold_count' in df.columns and df['sold_count'].notna().any()
        if has_sales:
            valid_sold = df['sold_count'].dropna()
            sales_cols = st.columns(4)
            with sales_cols[0]:
                st.metric("有销售数据产品", f"{len(valid_sold)} 个")
                if len(valid_sold) > 0:
                    st.metric("平均销量", f"{valid_sold.mean():.0f}")
                    st.metric("最高销量", f"{valid_sold.max():.0f}")
            with sales_cols[1]:
                if 'estimated_revenue' in df.columns:
                    valid_revenue = df['estimated_revenue'].dropna()
                    if len(valid_revenue) > 0:
                        st.metric("总估算销售额", f"${valid_revenue.sum():,.0f}")
                        st.metric("平均销售额", f"${valid_revenue.mean():,.0f}")
                        st.metric("最高销售额", f"${valid_revenue.max():,.0f}")
            with sales_cols[2]:
                if 'daily_sales_rate' in df.columns:
                    valid_rate = df['daily_sales_rate'].dropna()
                    if len(valid_rate) > 0:
                        st.metric("平均日均销量", f"{valid_rate.mean():.1f}/day")
                        st.metric("最高日均销量", f"{valid_rate.max():.1f}/day")
            with sales_cols[3]:
                if 'sales_label' in df.columns:
                    label_counts = df['sales_label'].dropna().value_counts()
                    for label, count in label_counts.items():
                        st.metric(label, f"{count} 个")

            chart_cols = st.columns(2)
            with chart_cols[0]:
                if 'estimated_revenue' in df.columns:
                    revenue_df = df[df['estimated_revenue'].notna()].nlargest(10, 'estimated_revenue')
                    if len(revenue_df) > 0:
                        fig = px.bar(
                            revenue_df,
                            x='estimated_revenue',
                            y=revenue_df['name'].apply(lambda x: str(x)[:30]),
                            orientation='h',
                            title="TOP 10 估算销售额",
                            labels={'estimated_revenue': '估算销售额 ($)', 'y': '产品'},
                        )
                        fig.update_layout(yaxis={'categoryorder': 'total ascending'}, height=400)
                        st.plotly_chart(fig, use_container_width=True)
            with chart_cols[1]:
                if 'daily_sales_rate' in df.columns:
                    rate_df = df[df['daily_sales_rate'].notna()].nlargest(10, 'daily_sales_rate')
                    if len(rate_df) > 0:
                        fig = px.bar(
                            rate_df,
                            x='daily_sales_rate',
                            y=rate_df['name'].apply(lambda x: str(x)[:30]),
                            orientation='h',
                            title="TOP 10 日均销量",
                            labels={'daily_sales_rate': '日均销量 (件/天)', 'y': '产品'},
                        )
                        fig.update_layout(yaxis={'categoryorder': 'total ascending'}, height=400)
                        st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("暂无销售数据（需要产品包含 Better Hurry / Selling Quickly 标签）")

    with st.expander("📦 库存与物流", expanded=False):
        inv_cols = st.columns(3)
        with inv_cols[0]:
            if 'stock_left' in df.columns:
                valid_stock = df['stock_left'].dropna()
                if len(valid_stock) > 0:
                    st.metric("有库存数据产品", f"{len(valid_stock)} 个")
                    st.metric("平均库存", f"{valid_stock.mean():.0f}")
                    st.metric("库存≤50", f"{len(valid_stock[valid_stock <= 50])} 个")
                    st.metric("库存≤100", f"{len(valid_stock[valid_stock <= 100])} 个")
                else:
                    st.info("暂无库存数据")
            if 'is_low_stock' in df.columns:
                low_stock_count = df['is_low_stock'].sum() if df['is_low_stock'].dtype == bool else (df['is_low_stock'] == True).sum()
                if low_stock_count > 0:
                    st.metric("低库存标记", f"{low_stock_count} 个")
        with inv_cols[1]:
            if 'shipping_type' in df.columns:
                valid_ship = df['shipping_type'].dropna()
                if len(valid_ship) > 0:
                    st.metric("有配送信息产品", f"{len(valid_ship)} 个")
                    ship_counts = valid_ship.value_counts()
                    fig = px.pie(
                        values=ship_counts.values,
                        names=ship_counts.index,
                        title="配送方式分布"
                    )
                    st.plotly_chart(fig, use_container_width=True)
        with inv_cols[2]:
            if 'is_sponsored' in df.columns:
                sponsored_count = df['is_sponsored'].sum() if df['is_sponsored'].dtype == bool else (df['is_sponsored'] == True).sum()
                st.metric("广告产品", f"{sponsored_count} 个")
            if 'is_best_seller' in df.columns:
                bestseller_count = df['is_best_seller'].sum() if df['is_best_seller'].dtype == bool else (df['is_best_seller'] == True).sum()
                st.metric("Best Seller", f"{bestseller_count} 个")

    with st.expander("🏆 TOP 5 推荐产品", expanded=True):
        top_products = df.nlargest(5, 'total_score') if 'total_score' in df.columns else df.head(5)
        for rank, (idx, row) in enumerate(top_products.iterrows(), 1):
            with st.container():
                top_cols = st.columns([1, 1, 4])
                with top_cols[0]:
                    st.markdown(f"### #{rank}")
                    if 'total_score' in row:
                        score = row.get('total_score', 0)
                        st.metric("总分", f"{score:.1f}")
                with top_cols[1]:
                    image_url = row.get('image_url', '')
                    if image_url and pd.notna(image_url) and str(image_url).startswith('http'):
                        st.image(str(image_url), use_container_width=True)
                    else:
                        st.markdown("<div style='width:100%;height:120px;background:#f0f0f0;border-radius:8px;display:flex;align-items:center;justify-content:center;color:#999;font-size:24px;'>📦</div>", unsafe_allow_html=True)
                with top_cols[2]:
                    name = row.get('name', '未知产品')
                    product_url = row.get('url', '')
                    if product_url and pd.notna(product_url) and str(product_url).startswith('http'):
                        st.markdown(f"**[{name}]({product_url})** 📎")
                    else:
                        st.markdown(f"**{name}**")
                    detail_parts = []
                    if pd.notna(row.get('price')):
                        detail_parts.append(f"💰 ${row['price']:.2f}")
                    if pd.notna(row.get('rating')):
                        detail_parts.append(f"⭐ {row['rating']}")
                    if pd.notna(row.get('review_count')):
                        detail_parts.append(f"💬 {int(row['review_count'])}")
                    if pd.notna(row.get('sold_count')) and row.get('sold_count'):
                        detail_parts.append(f"🔥 {int(row['sold_count'])} sold")
                    if pd.notna(row.get('page_rank')) and row.get('page_rank'):
                        detail_parts.append(f"📊 #{int(row['page_rank'])}")
                    if pd.notna(row.get('estimated_revenue')) and row.get('estimated_revenue'):
                        detail_parts.append(f"💵 ${row['estimated_revenue']:,.0f}")
                    if row.get('is_best_seller') is True:
                        detail_parts.append("🏆 Best Seller")
                    if detail_parts:
                        st.markdown(" | ".join(detail_parts))
                    rec = row.get('recommendation', '')
                    if rec:
                        rec_emoji = {'强烈推荐': '🟢', '推荐': '🔵', '可以考虑': '🟡', '谨慎考虑': '🟠', '不推荐': '🔴'}.get(rec, '⚪')
                        st.markdown(f"{rec_emoji} **{rec}**")
                    if product_url and pd.notna(product_url) and str(product_url).startswith('http'):
                        st.markdown(f"[🔗 查看产品详情]({product_url})")
                st.markdown("---")

    st.markdown("---")

    st.subheader("💾 导出数据")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("📥 导出为 Excel", use_container_width=True):
            output_file = f"wayfair_analysis_{time.strftime('%Y%m%d_%H%M%S')}.xlsx"
            df.to_excel(output_file, index=False, engine='openpyxl')
            st.success(f"已导出到: {output_file}")

    with col2:
        if st.button("📄 导出为 CSV", use_container_width=True):
            output_file = f"wayfair_analysis_{time.strftime('%Y%m%d_%H%M%S')}.csv"
            df.to_csv(output_file, index=False, encoding='utf-8-sig')
            st.success(f"已导出到: {output_file}")

else:
    st.info("👈 请先在左侧抓取或导入数据，然后点击'开始分析'")

    st.markdown("---")

    st.subheader("📖 使用指南")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("""
        ### 🌐 Wayfair 提取 (推荐)

        1. 用浏览器打开 wayfair.com
        2. 搜索产品关键词
        3. 按 Ctrl+S 保存网页
        4. 上传 HTML 文件
        5. 系统自动提取数据!

        **优势:**
        - 无需任何自动化
        - 不会被拦截
        - 最简单可靠
        """)

    with col2:
        st.markdown("""
        ### 🏠 Home Depot 提取

        1. 用浏览器打开 homedepot.com
        2. 搜索产品关键词
        3. 按 Ctrl+S 保存网页
        4. 上传 HTML 文件
        5. 系统自动提取数据!

        **优势:**
        - 同样无需自动化
        - 支持多平台数据合并分析
        """)

    with col3:
        st.markdown("""
        ### 📂 手动导入

        1. 准备 Excel/CSV 文件
        2. 上传文件
        3. 确认数据格式正确
        4. 点击「开始分析」

        **数据格式:**
        - name (必填)
        - price (必填)
        - original_price (选填)
        - rating (选填)
        - review_count (选填)
        """)

st.markdown("---")
st.markdown("💡 支持 Wayfair + Home Depot 多平台数据: 浏览网页 → Ctrl+S 保存 → 上传 HTML → 自动提取 → 合并分析")