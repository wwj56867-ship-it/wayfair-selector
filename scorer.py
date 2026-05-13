import pandas as pd
import numpy as np


class ProductScorer:
    WEIGHT_LABELS = {
        'price_score': '价格区间',
        'profit_margin_score': '利润空间',
        'competition_score': '竞争程度',
        'demand_score': '市场需求',
        'rating_score': '产品评分',
        'review_score': '评论趋势',
        'discount_score': '折扣力度',
        'name_length_score': '标题优化',
        'market_opportunity_score': '市场机会',
    }

    WEIGHT_DESCRIPTIONS = {
        'price_score': '价格是否在最佳区间 ($50-$200)',
        'profit_margin_score': '原价与现价的差额比例',
        'competition_score': '评论越少竞争越小 (反向)',
        'demand_score': '评论越多需求越大',
        'rating_score': '产品评分高低',
        'review_score': '评论数是否在增长区间',
        'discount_score': '折扣是否在合理范围',
        'name_length_score': '标题长度是否利于SEO',
        'market_opportunity_score': '低评分高评论=改进机会',
    }

    DEFAULT_WEIGHTS = {
        'price_score': 0.15,
        'profit_margin_score': 0.20,
        'competition_score': 0.15,
        'demand_score': 0.15,
        'rating_score': 0.10,
        'review_score': 0.10,
        'discount_score': 0.05,
        'name_length_score': 0.05,
        'market_opportunity_score': 0.05,
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
        df['profit_margin_score'] = df.apply(lambda x: self.score_profit_margin(x.get('price'), x.get('original_price')), axis=1)
        df['competition_score'] = df['review_count'].apply(self.score_competition)
        df['demand_score'] = df['review_count'].apply(self.score_demand)
        df['rating_score'] = df['rating'].apply(self.score_rating)
        df['review_score'] = df['review_count'].apply(self.score_review_trend)
        df['discount_score'] = df.apply(lambda x: self.score_discount(x.get('price'), x.get('original_price')), axis=1)
        df['name_length_score'] = df['name'].apply(self.score_name_length)
        df['market_opportunity_score'] = df.apply(lambda x: self.score_market_opportunity(
            x.get('rating'), x.get('review_count'), x.get('price')
        ), axis=1)
        
        df['total_score'] = sum(
            df[col] * weight 
            for col, weight in self.weights.items()
        )
        
        df['recommendation'] = df['total_score'].apply(self.get_recommendation)
        
        return df
    
    def score_price(self, price):
        if not price or price <= 0:
            return 0
        
        if 50 <= price <= 200:
            return 100
        elif 30 <= price < 50 or 200 < price <= 300:
            return 80
        elif 20 <= price < 30 or 300 < price <= 500:
            return 60
        else:
            return 40
    
    def score_profit_margin(self, price, original_price):
        if not price or not original_price or price <= 0 or original_price <= 0:
            return 50
        
        discount_rate = (original_price - price) / original_price
        
        if discount_rate >= 0.4:
            return 100
        elif discount_rate >= 0.3:
            return 85
        elif discount_rate >= 0.2:
            return 70
        elif discount_rate >= 0.1:
            return 55
        else:
            return 40
    
    def score_competition(self, review_count):
        if review_count is None:
            return 50
        
        if review_count < 50:
            return 95
        elif review_count < 100:
            return 85
        elif review_count < 200:
            return 70
        elif review_count < 500:
            return 50
        elif review_count < 1000:
            return 30
        else:
            return 15
    
    def score_demand(self, review_count):
        if review_count is None:
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
        if not rating or rating <= 0:
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
        if review_count is None:
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
        if not price or not original_price or price <= 0 or original_price <= 0:
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
    
    def score_name_length(self, name):
        if not name:
            return 50
        
        length = len(name)
        
        if 30 <= length <= 80:
            return 100
        elif 20 <= length < 30 or 80 < length <= 100:
            return 80
        elif 10 <= length < 20:
            return 60
        else:
            return 40
    
    def score_market_opportunity(self, rating, review_count, price):
        if not rating or not review_count or not price:
            return 50
        
        score = 0
        
        if rating < 4.2 and review_count > 100:
            score += 40
        elif rating < 4.5 and review_count > 50:
            score += 30
        
        if 40 <= price <= 150:
            score += 30
        elif 30 <= price < 40 or 150 < price <= 250:
            score += 20
        
        if review_count < 300:
            score += 30
        elif review_count < 500:
            score += 20
        
        return min(score, 100)
    
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
            report.append(f"   建议: {row.get('recommendation', '无')}")
        
        return "\n".join(report)
