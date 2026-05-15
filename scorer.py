import pandas as pd
import numpy as np
import re
from collections import Counter


class ProductScorer:
    WEIGHT_LABELS = {
        'price_score': '价格区间',
        'demand_score': '市场需求',
        'rating_score': '产品评分',
        'review_score': '评论趋势',
        'discount_score': '折扣力度',
        'sales_urgency_score': '销售紧迫性',
    }

    WEIGHT_DESCRIPTIONS = {
        'price_score': '价格是否在最佳区间 ($50-$200)',
        'demand_score': '评论越多需求越大',
        'rating_score': '产品评分高低',
        'review_score': '评论数是否在增长区间',
        'discount_score': '折扣是否在合理范围',
        'sales_urgency_score': '"Better Hurry" 销量越高紧迫性越强',
    }

    DEFAULT_WEIGHTS = {
        'price_score': 0.20,
        'demand_score': 0.20,
        'rating_score': 0.15,
        'review_score': 0.15,
        'discount_score': 0.10,
        'sales_urgency_score': 0.20,
    }

    def __init__(self, weights=None):
        if weights:
            total = sum(weights.values())
            if total > 0:
                self.weights = {k: v / total for k, v in weights.items()}
            else:
                self.weights = self.DEFAULT_WEIGHTS.copy()
        else:
            self.weights = self.DEFAULT_WEIGHTS.copy()
    
    def calculate_all_scores(self, df):
        if df.empty:
            return df
        
        df = df.copy()
        
        df['price_score'] = df['price'].apply(self.score_price)
        df['demand_score'] = df['review_count'].apply(self.score_demand)
        df['rating_score'] = df['rating'].apply(self.score_rating)
        df['review_score'] = df['review_count'].apply(self.score_review_trend)
        df['discount_score'] = df.apply(lambda x: self.score_discount(x.get('price'), x.get('original_price')), axis=1)
        df['sales_urgency_score'] = df.apply(lambda x: self.score_sales_urgency(
            x.get('sold_count'), x.get('sold_days')
        ), axis=1)
        
        df['total_score'] = sum(
            df[col] * weight 
            for col, weight in self.weights.items()
        )
        
        df['recommendation'] = df['total_score'].apply(self.get_recommendation)
        
        return df
    
    def score_price(self, price):
        if pd.isna(price) or not price or price <= 0:
            return 0
        
        if 50 <= price <= 200:
            return 100
        elif 30 <= price < 50 or 200 < price <= 300:
            return 80
        elif 20 <= price < 30 or 300 < price <= 500:
            return 60
        else:
            return 40
    
    def score_demand(self, review_count):
        if pd.isna(review_count) or review_count is None:
            return 50
        
        if review_count >= 500:
            return 100
        elif review_count >= 200:
            return 85
        elif review_count >= 100:
            return 70
        elif review_count >= 50:
            return 55
        elif review_count >= 20:
            return 40
        else:
            return 25
    
    def score_rating(self, rating):
        if pd.isna(rating) or not rating or rating <= 0:
            return 50
        
        if rating >= 4.8:
            return 100
        elif rating >= 4.5:
            return 90
        elif rating >= 4.0:
            return 75
        elif rating >= 3.5:
            return 60
        else:
            return 40
    
    def score_review_trend(self, review_count):
        if pd.isna(review_count) or review_count is None:
            return 50
        
        if 100 <= review_count <= 500:
            return 100
        elif 50 <= review_count < 100:
            return 85
        elif 200 <= review_count <= 800:
            return 75
        elif review_count < 50:
            return 60
        else:
            return 50
    
    def score_discount(self, price, original_price):
        if pd.isna(price) or pd.isna(original_price) or not price or not original_price or price <= 0 or original_price <= 0:
            return 50
        
        discount_rate = (original_price - price) / original_price
        
        if 0.2 <= discount_rate <= 0.5:
            return 100
        elif 0.1 <= discount_rate < 0.2:
            return 70
        elif discount_rate > 0.5:
            return 60
        else:
            return 40
    
    def score_sales_urgency(self, sold_count, sold_days):
        if pd.isna(sold_count) or not sold_count or sold_count <= 0:
            return 50

        if pd.isna(sold_days) or not sold_days or sold_days <= 0:
            sold_days = 5

        daily_rate = sold_count / sold_days

        if daily_rate >= 30:
            return 100
        elif daily_rate >= 20:
            return 90
        elif daily_rate >= 10:
            return 80
        elif daily_rate >= 5:
            return 70
        elif daily_rate >= 3:
            return 60
        elif daily_rate >= 1:
            return 55
        else:
            return 50

    def get_recommendation(self, total_score):
        if total_score >= 80:
            return '强烈推荐'
        elif total_score >= 70:
            return '推荐'
        elif total_score >= 60:
            return '可以考虑'
        elif total_score >= 50:
            return '谨慎考虑'
        else:
            return '不推荐'
    
    def generate_analysis_report(self, df):
        if df.empty:
            return "无数据可分析"
        
        report = []
        report.append("=" * 50)
        report.append("选品分析报告")
        report.append("=" * 50)
        report.append(f"\n分析产品总数: {len(df)}")
        
        if 'total_score' in df.columns:
            report.append(f"\n推荐产品数:")
            report.append(f"  强烈推荐: {len(df[df['recommendation'] == '强烈推荐'])}")
            report.append(f"  推荐: {len(df[df['recommendation'] == '推荐'])}")
            report.append(f"  可以考虑: {len(df[df['recommendation'] == '可以考虑'])}")
            report.append(f"  谨慎考虑: {len(df[df['recommendation'] == '谨慎考虑'])}")
            report.append(f"  不推荐: {len(df[df['recommendation'] == '不推荐'])}")
        
        if 'price' in df.columns:
            valid_prices = df['price'].dropna()
            if len(valid_prices) > 0:
                report.append(f"\n价格区间:")
                report.append(f"  最低价: ${valid_prices.min():.2f}")
                report.append(f"  最高价: ${valid_prices.max():.2f}")
                report.append(f"  平均价: ${valid_prices.mean():.2f}")
        
        if 'rating' in df.columns:
            valid_ratings = df['rating'].dropna()
            if len(valid_ratings) > 0:
                report.append(f"\n评分分布:")
                report.append(f"  平均评分: {valid_ratings.mean():.2f}")
                report.append(f"  4.5分以上: {len(valid_ratings[valid_ratings >= 4.5])}")
                report.append(f"  4.0-4.5分: {len(valid_ratings[(valid_ratings >= 4.0) & (valid_ratings < 4.5)])}")
        
        if 'review_count' in df.columns:
            valid_reviews = df['review_count'].dropna()
            if len(valid_reviews) > 0:
                report.append(f"\n评论数分布:")
                report.append(f"  平均评论数: {valid_reviews.mean():.0f}")
                report.append(f"  100以下: {len(valid_reviews[valid_reviews < 100])}")
                report.append(f"  100-500: {len(valid_reviews[(valid_reviews >= 100) & (valid_reviews < 500)])}")
                report.append(f"  500以上: {len(valid_reviews[valid_reviews >= 500])}")

        if 'sold_count' in df.columns:
            valid_sold = df['sold_count'].dropna()
            if len(valid_sold) > 0:
                report.append(f"\n销售紧迫性 (Better Hurry):")
                report.append(f"  有销售数据的产品: {len(valid_sold)}")
                report.append(f"  平均销量: {valid_sold.mean():.0f}")
                report.append(f"  最高销量: {valid_sold.max():.0f}")
                report.append(f"  日均销量>=10: {len(valid_sold[valid_sold >= 50])}")

        if 'stock_left' in df.columns:
            valid_stock = df['stock_left'].dropna()
            if len(valid_stock) > 0:
                report.append(f"\n库存状况:")
                report.append(f"  有库存数据的产品: {len(valid_stock)}")
                report.append(f"  平均库存: {valid_stock.mean():.0f}")
                report.append(f"  库存<=50: {len(valid_stock[valid_stock <= 50])}")
                report.append(f"  库存<=100: {len(valid_stock[valid_stock <= 100])}")

        if 'is_low_stock' in df.columns:
            low_stock_count = df['is_low_stock'].sum() if df['is_low_stock'].dtype == bool else (df['is_low_stock'] == True).sum()
            if low_stock_count > 0:
                report.append(f"  低库存标记: {low_stock_count} 个产品")

        if 'shipping_type' in df.columns:
            valid_ship = df['shipping_type'].dropna()
            if len(valid_ship) > 0:
                report.append(f"\n物流配送:")
                report.append(f"  有配送信息的产品: {len(valid_ship)}")
                ship_counts = valid_ship.value_counts()
                for stype, count in ship_counts.items():
                    report.append(f"  {stype}: {count} 个产品")

        if 'is_sponsored' in df.columns:
            sponsored_count = df['is_sponsored'].sum() if df['is_sponsored'].dtype == bool else (df['is_sponsored'] == True).sum()
            if sponsored_count > 0:
                report.append(f"\n广告产品: {sponsored_count} 个 (付费推广)")

        if 'is_best_seller' in df.columns:
            bestseller_count = df['is_best_seller'].sum() if df['is_best_seller'].dtype == bool else (df['is_best_seller'] == True).sum()
            if bestseller_count > 0:
                report.append(f"\nBest Seller 产品: {bestseller_count} 个")

        if 'estimated_revenue' in df.columns:
            valid_revenue = df['estimated_revenue'].dropna()
            if len(valid_revenue) > 0:
                report.append(f"\n销售额估算 (基于 Better Hurry 数据):")
                report.append(f"  有销售数据的产品: {len(valid_revenue)}")
                report.append(f"  总估算销售额: ${valid_revenue.sum():,.0f}")
                report.append(f"  平均估算销售额: ${valid_revenue.mean():,.0f}")
                report.append(f"  最高估算销售额: ${valid_revenue.max():,.0f}")

        if 'daily_sales_rate' in df.columns:
            valid_rate = df['daily_sales_rate'].dropna()
            if len(valid_rate) > 0:
                report.append(f"\n日均销量:")
                report.append(f"  平均日均销量: {valid_rate.mean():.1f}/day")
                report.append(f"  最高日均销量: {valid_rate.max():.1f}/day")
        
        report.append("\n" + "=" * 50)
        report.append("TOP 5 推荐产品:")
        report.append("=" * 50)
        
        top_products = df.nlargest(5, 'total_score') if 'total_score' in df.columns else df.head(5)
        
        for idx, row in top_products.iterrows():
            report.append(f"\n{idx + 1}. {row.get('name', '未知产品')}")
            report.append(f"   总分: {row.get('total_score', 0):.1f}")
            report.append(f"   价格: ${row.get('price', 0):.2f}")
            report.append(f"   评分: {row.get('rating', 0)}")
            report.append(f"   评论数: {row.get('review_count', 0)}")
            sold_count = row.get('sold_count')
            sold_days = row.get('sold_days')
            if pd.notna(sold_count) and sold_count:
                report.append(f"   销售紧迫性: {int(sold_count)} sold in {int(sold_days) if pd.notna(sold_days) else '?'} days")
            page_rank = row.get('page_rank')
            if pd.notna(page_rank) and page_rank:
                report.append(f"   搜索排名: #{int(page_rank)}")
            estimated_revenue = row.get('estimated_revenue')
            if pd.notna(estimated_revenue) and estimated_revenue:
                report.append(f"   估算销售额: ${estimated_revenue:,.0f}")
            daily_sales_rate = row.get('daily_sales_rate')
            if pd.notna(daily_sales_rate) and daily_sales_rate:
                report.append(f"   日均销量: {daily_sales_rate:.1f}/day")
            is_best_seller = row.get('is_best_seller')
            if is_best_seller is True:
                report.append(f"   🏆 Best Seller")
            report.append(f"   建议: {row.get('recommendation', '无')}")
        
        return "\n".join(report)


class KeywordExtractor:
    PIECE_PATTERNS = [
        r'\d+\s+Piece',
    ]
    PERSON_PATTERNS = [
        r'\d+\s+Person',
    ]
    PRODUCT_TYPE_PATTERNS = [
        r'Outdoor\s+Seating\s+Group',
        r'Outdoor\s+Dining\s+Set',
        r'Conversation\s+Set',
        r'Dining\s+Set',
        r'Seating\s+Group',
        r'Sofa\s+Set',
        r'Sectional\s+Set',
        r'Lounge\s+Set',
        r'Chat\s+Set',
        r'Fire\s+Pit\s+Set',
        r'Fire\s+Pit\s+Table',
        r'Bistro\s+Set',
        r'Bar\s+Set',
        r'Pub\s+Set',
        r'Counter\s+Set',
        r'Patio\s+Set',
        r'Patio\s+Sofa',
        r'Patio\s+Chair',
        r'Patio\s+Table',
        r'Patio\s+Bench',
        r'Patio\s+Lounge',
        r'Patio\s+Sectional',
        r'Patio\s+Chaise',
        r'Patio\s+Ottoman',
        r'Patio\s+Bar\s+Set',
        r'Patio\s+Dining\s+Set',
        r'Garden\s+Set',
        r'Garden\s+Bench',
        r'Loveseat',
        r'Sofa\s+Bed',
        r'Sleeper\s+Sofa',
        r'Reclining\s+Sofa',
        r'Chaise\s+Lounge',
        r'Accent\s+Chair',
        r'Arm\s+Chair',
        r'Club\s+Chair',
        r'Wingback\s+Chair',
        r'Side\s+Chair',
        r'Dining\s+Chair',
        r'Bar\s+Stool',
        r'Counter\s+Stool',
        r'Console\s+Table',
        r'Coffee\s+Table',
        r'End\s+Table',
        r'Side\s+Table',
        r'Dining\s+Table',
        r'Bar\s+Table',
        r'Counter\s+Table',
        r'Fire\s+Pit',
        r'Fire\s+Table',
        r'Ottoman',
        r'Bench',
        r'Daybed',
        r'Futon',
        r'Hammock',
        r'Swing',
        r'Porch\s+Swing',
        r'Storage\s+Bench',
        r'Shoe\s+Bench',
        r'Entryway\s+Bench',
        r'Bed\s+Frame',
        r'Headboard',
        r'Dresser',
        r'Chest\s+of\s+Drawers',
        r'Nightstand',
        r'Bookcase',
        r'Shelf',
        r'Shelving\s+Unit',
        r'Cabinet',
        r'TV\s+Stand',
        r'Entertainment\s+Center',
        r'Desk',
        r'Office\s+Chair',
        r'Filing\s+Cabinet',
        r'Rug',
        r'Area\s+Rug',
        r'Runner\s+Rug',
        r'Mirror',
        r'Wall\s+Mirror',
        r'Floor\s+Mirror',
        r'Lamp',
        r'Floor\s+Lamp',
        r'Table\s+Lamp',
        r'Pendant',
        r'Chandelier',
        r'Sconce',
        r'Ceiling\s+Fan',
    ]
    LOCATION_PATTERNS = [
        r'Outdoor',
        r'Indoor',
        r'Patio',
        r'Garden',
        r'Backyard',
        r'Poolside',
        r'Balcony',
        r'Porch',
        r'Deck',
        r'Yard',
        r'Kitchen',
        r'Bathroom',
        r'Bedroom',
        r'Living\s+Room',
        r'Dining\s+Room',
        r'Entryway',
        r'Office',
        r'Laundry',
    ]
    MATERIAL_PATTERNS = [
        r'Wicker',
        r'Rattan',
        r'Teak',
        r'Aluminum',
        r'Steel',
        r'Cast\s+Aluminum',
        r'Forged\s+Aluminum',
        r'Stainless\s+Steel',
        r'Wrought\s+Iron',
        r'Iron',
        r'Wood',
        r'Solid\s+Wood',
        r'Engineered\s+Wood',
        r'MDF',
        r'Plywood',
        r'Oak',
        r'Walnut',
        r'Pine',
        r'Mahogany',
        r'Acacia',
        r'Eucalyptus',
        r'Cedar',
        r'Bamboo',
        r'Resin',
        r'Plastic',
        r'Faux\s+Wood',
        r'Concrete',
        r'Stone',
        r'Marble',
        r'Glass',
        r'Velvet',
        r'Leather',
        r'Faux\s+Leather',
        r'Linen',
        r'Cotton',
        r'Microfiber',
        r'Polyester',
        r'Sunbrella',
        r'Olefin',
    ]
    COLOR_PATTERNS = [
        r'White',
        r'Black',
        r'Gray',
        r'Grey',
        r'Brown',
        r'Beige',
        r'Blue',
        r'Red',
        r'Green',
        r'Yellow',
        r'Orange',
        r'Pink',
        r'Purple',
        r'Gold',
        r'Silver',
        r'Bronze',
        r'Navy',
        r'Teal',
        r'Ivory',
        r'Cream',
        r'Tan',
        r'Charcoal',
        r'Espresso',
        r'Natural',
        r'Taupe',
        r'Rust',
        r'Terracotta',
        r'Sage',
    ]
    STYLE_PATTERNS = [
        r'Modern',
        r'Contemporary',
        r'Traditional',
        r'Rustic',
        r'Industrial',
        r'Farmhouse',
        r'Mid-Century',
        r'Mid\s+Century',
        r'Minimalist',
        r'Bohemian',
        r'Coastal',
        r'Scandinavian',
        r'Vintage',
        r'Retro',
        r'Classic',
        r'Transitional',
        r'Glam',
        r'Eclectic',
        r'Country',
        r'Cottage',
        r'Mission',
        r'Craftsman',
        r'Colonial',
        r'Victorian',
        r'Mediterranean',
        r'Tropical',
        r'Asian',
        r'Art\s+Deco',
    ]
    FEATURE_PATTERNS = [
        r'with\s+Cushions',
        r'with\s+Fire\s+Pit',
        r'with\s+Umbrella',
        r'with\s+Ottoman',
        r'with\s+Cover',
        r'with\s+Pillows',
        r'with\s+Glass\s+Top',
        r'with\s+Storage',
        r'with\s+Shelf',
        r'with\s+Drawers',
        r'with\s+Doors',
        r'with\s+LED',
        r'with\s+Lights',
        r'with\s+Fan',
        r'with\s+Heater',
        r'Adjustable',
        r'Folding',
        r'Foldable',
        r'Stackable',
        r'Extendable',
        r'Reclining',
        r'Swivel',
        r'Rocking',
        r'Gliding',
        r'Rolling',
        r'Wheeled',
        r'Weather\s+Resistant',
        r'Water\s+Resistant',
        r'Rust\s+Resistant',
        r'UV\s+Resistant',
        r'Fade\s+Resistant',
    ]

    def __init__(self):
        self.all_patterns = []
        self.pattern_labels = {}
        pattern_groups = [
            ('piece', self.PIECE_PATTERNS),
            ('person', self.PERSON_PATTERNS),
            ('product_type', self.PRODUCT_TYPE_PATTERNS),
            ('location', self.LOCATION_PATTERNS),
            ('material', self.MATERIAL_PATTERNS),
            ('color', self.COLOR_PATTERNS),
            ('style', self.STYLE_PATTERNS),
            ('feature', self.FEATURE_PATTERNS),
        ]
        for label, patterns in pattern_groups:
            for p in patterns:
                compiled = re.compile(r'\b' + p + r'\b', re.IGNORECASE)
                self.all_patterns.append((p, compiled, label))
                self.pattern_labels[p] = label

    def extract_segments(self, title):
        if not title or not isinstance(title, str):
            return []
        segments = []
        seen_spans = set()
        matched_raw = []
        for pattern_str, compiled, label in self.all_patterns:
            for m in compiled.finditer(title):
                span = m.span()
                if not any(s <= span[0] < e or s < span[1] <= e for s, e in seen_spans if not (span[1] <= s or span[0] >= e)):
                    raw_text = m.group()
                    segments.append({
                        'text': raw_text,
                        'category': label,
                        'start': span[0],
                        'end': span[1],
                    })
                    seen_spans.add(span)
                    matched_raw.append(raw_text)
        segments.sort(key=lambda x: x['start'])
        return segments

    def analyze_dataframe(self, df):
        if df.empty or 'name' not in df.columns:
            return df, {}
        all_segments = []
        for idx, row in df.iterrows():
            segments = self.extract_segments(row.get('name', ''))
            all_segments.append(segments)
        df = df.copy()
        df['segments'] = all_segments
        df['segment_texts'] = [', '.join(s['text'] for s in segs) for segs in all_segments]
        seg_by_cat = {}
        for segs in all_segments:
            for seg in segs:
                cat = seg['category']
                text = seg['text']
                if cat not in seg_by_cat:
                    seg_by_cat[cat] = {}
                if text not in seg_by_cat[cat]:
                    seg_by_cat[cat][text] = 0
                seg_by_cat[cat][text] += 1
        for cat in seg_by_cat:
            seg_by_cat[cat] = dict(sorted(seg_by_cat[cat].items(), key=lambda x: x[1], reverse=True))
        return df, seg_by_cat

    def get_segment_analytics(self, df):
        if df.empty or 'segments' not in df.columns:
            return pd.DataFrame()
        rows = []
        seen = set()
        for idx, row in df.iterrows():
            for seg in row.get('segments', []):
                text = seg['text']
                cat = seg['category']
                key = (text, cat)
                if key not in seen:
                    seen.add(key)
                    matching = df[df['segments'].apply(lambda s: any(seg2['text'] == text for seg2 in s))]
                    price_vals = matching['price'].dropna() if 'price' in matching.columns else pd.Series()
                    score_vals = matching['total_score'].dropna() if 'total_score' in matching.columns else pd.Series()
                    rating_vals = matching['rating'].dropna() if 'rating' in matching.columns else pd.Series()
                    rows.append({
                        'segment': text,
                        'category': cat,
                        'count': len(matching),
                        'avg_price': price_vals.mean() if len(price_vals) > 0 else None,
                        'avg_score': score_vals.mean() if len(score_vals) > 0 else None,
                        'avg_rating': rating_vals.mean() if len(rating_vals) > 0 else None,
                    })
        result = pd.DataFrame(rows)
        if not result.empty:
            result = result.sort_values('count', ascending=False).reset_index(drop=True)
        return result
