import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from scorer import ProductScorer
from bs4 import BeautifulSoup
import time
import re
import json


st.set_page_config(
    page_title="Wayfair 选品分析系统",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("🎯 Wayfair 跨境电商选品分析系统")
st.markdown("---")


if 'products_data' not in st.session_state:
    st.session_state.products_data = None

if 'analyzed_data' not in st.session_state:
    st.session_state.analyzed_data = None


def extract_wayfair_html(html_content):
    products = []
    soup = BeautifulSoup(html_content, 'html.parser')

    card_items = soup.select('[data-node-id*="ListingCollectionItem"]')
    if card_items:
        seen_urls = set()
        for item in card_items:
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

                if name and price:
                    products.append({
                        'name': name,
                        'price': price,
                        'original_price': was_price,
                        'rating': rating,
                        'review_count': reviews,
                        'brand': brand,
                        'url': url,
                        'image_url': image_url,
                    })
            except Exception:
                continue

    if not products:
        banners = soup.select('[data-enzyme-id*="Product-Banner-Container"]')
        if banners:
            seen_urls = set()
            for banner in banners:
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

                    if name and price:
                        products.append({
                            'name': name,
                            'price': price,
                            'original_price': was_price,
                            'rating': rating,
                            'review_count': reviews,
                            'brand': '',
                            'url': url,
                            'image_url': _extract_img_url_from_container(banner),
                        })
                except Exception:
                    continue

    if not products:
        pdp_links = soup.find_all('a', href=re.compile(r'/pdp/'))
        if pdp_links:
            seen_urls = set()
            for link_el in pdp_links:
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
                        products.append({
                            'name': name,
                            'price': price,
                            'original_price': was_price,
                            'rating': rating,
                            'review_count': reviews,
                            'brand': '',
                            'url': url,
                            'image_url': image_url,
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

            for item in items:
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
                            products.append({
                                'name': product_name,
                                'price': product_price,
                                'original_price': product_orig,
                                'rating': product_rating,
                                'review_count': product_reviews,
                                'brand': '',
                                'url': product_url,
                                'image_url': product_image,
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


with st.sidebar:
    st.header("🔧 控制面板")

    tab1, tab2 = st.tabs(["🌐 网页提取", "📂 手动导入"])

    with tab1:
        st.subheader("从 Wayfair 网页提取数据")
        st.markdown("**最可靠的方式! 无需任何自动化,不会被拦截**")

        with st.expander("📖 操作步骤 (点击展开)", expanded=True):
            st.markdown("""
            **第一步: 打开 Wayfair**
            1. 用浏览器打开 [wayfair.com](https://www.wayfair.com)
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
            ["自定义", "均衡模式", "利润优先", "蓝海市场", "高需求优先", "评分优先"],
            index=0,
            help="选择预设权重方案,或自定义调整"
        )

        presets = {
            "均衡模式": {
                'price_score': 0.11, 'profit_margin_score': 0.11, 'competition_score': 0.11,
                'demand_score': 0.11, 'rating_score': 0.11, 'review_score': 0.11,
                'discount_score': 0.11, 'name_length_score': 0.11, 'market_opportunity_score': 0.12,
            },
            "利润优先": {
                'price_score': 0.10, 'profit_margin_score': 0.35, 'competition_score': 0.10,
                'demand_score': 0.10, 'rating_score': 0.05, 'review_score': 0.05,
                'discount_score': 0.15, 'name_length_score': 0.03, 'market_opportunity_score': 0.07,
            },
            "蓝海市场": {
                'price_score': 0.05, 'profit_margin_score': 0.10, 'competition_score': 0.35,
                'demand_score': 0.05, 'rating_score': 0.05, 'review_score': 0.05,
                'discount_score': 0.05, 'name_length_score': 0.05, 'market_opportunity_score': 0.25,
            },
            "高需求优先": {
                'price_score': 0.05, 'profit_margin_score': 0.10, 'competition_score': 0.05,
                'demand_score': 0.35, 'rating_score': 0.10, 'review_score': 0.15,
                'discount_score': 0.05, 'name_length_score': 0.05, 'market_opportunity_score': 0.10,
            },
            "评分优先": {
                'price_score': 0.05, 'profit_margin_score': 0.10, 'competition_score': 0.05,
                'demand_score': 0.10, 'rating_score': 0.35, 'review_score': 0.10,
                'discount_score': 0.05, 'name_length_score': 0.05, 'market_opportunity_score': 0.15,
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
                key=f"weight_{key}"
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
                st.session_state.analyzed_data = analyzed
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
    df = st.session_state.analyzed_data.copy()

    if 'min_score' in locals():
        df = df[df['total_score'] >= min_score]

    if 'price_range' in locals():
        df = df[(df['price'] >= price_range[0]) & (df['price'] <= price_range[1])]

    if 'recommendation_filter' in locals() and len(recommendation_filter) > 0:
        df = df[df['recommendation'].isin(recommendation_filter)]

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

    tab1, tab2, tab3, tab4 = st.tabs(["价格分布", "评分分析", "选品指标雷达图", "推荐产品列表"])

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
            st.subheader("TOP 10 产品多维度分析")

            top_10 = df.nlargest(10, 'total_score')

            metrics_to_show = ['price_score', 'profit_margin_score', 'competition_score',
                             'demand_score', 'rating_score']

            available_metrics = [m for m in metrics_to_show if m in df.columns]

            if available_metrics:
                fig = go.Figure()

                for idx, row in top_10.iterrows():
                    fig.add_trace(go.Scatterpolar(
                        r=[row[m] for m in available_metrics],
                        theta=[m.replace('_score', '').replace('_', ' ').title() for m in available_metrics],
                        name=row.get('name', '')[:30],
                    ))

                fig.update_layout(
                    polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
                    showlegend=True,
                    title="TOP 10 产品雷达图对比"
                )
                st.plotly_chart(fig, use_container_width=True)

    with tab4:
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

                        st.markdown(f"**{name}**")
                        st.markdown(f"${price:.2f} | ⭐{rating} | {rec_emoji}{rec}")
                        st.markdown(f"综合评分: **{score:.1f}**")

                        url = row.get('url', '')
                        if url and isinstance(url, str) and url.startswith('http'):
                            st.markdown(f"[查看详情 ↗]({url})")

            st.markdown("---")

        display_cols = ['name', 'price', 'rating', 'review_count', 'total_score', 'recommendation']
        available_cols = [c for c in display_cols if c in df.columns]

        df_display = df[available_cols].copy()

        if 'name' in df_display.columns:
            df_display['name'] = df_display['name'].apply(lambda x: str(x)[:50] + '...' if len(str(x)) > 50 else x)

        if 'price' in df_display.columns:
            df_display['price'] = df_display['price'].apply(lambda x: f"${x:.2f}" if pd.notna(x) else '-')

        if 'total_score' in df_display.columns:
            df_display['total_score'] = df_display['total_score'].apply(lambda x: f"{x:.1f}")

        st.dataframe(df_display, use_container_width=True, height=400)

    st.markdown("---")

    st.subheader("📋 详细分析报告")

    scorer = ProductScorer()
    report = scorer.generate_analysis_report(df)
    st.text(report)

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

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("""
        ### 🌐 方式一: 网页提取 (推荐)

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
        ### 📂 方式二: 手动导入

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
st.markdown("💡 推荐使用「网页提取」方式: 手动浏览 Wayfair → Ctrl+S 保存 → 上传 HTML → 自动提取数据")
