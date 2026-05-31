#!/usr/bin/env python3
"""AI 日报全流程脚本：从 AI HOT (aihot.virxact.com) 获取真实日报内容 → 生成图片/文案 → 推送飞书群。

同时兼容 Windows 本地运行 和 GitHub Actions Linux runner。
GitHub Actions 通过环境变量注入凭据：
  FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_CHAT_ID
"""

import json, os, sys, textwrap, random, argparse
from datetime import datetime
from pathlib import Path
from io import BytesIO

import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# ── 常量 ──────────────────────────────────────────────────
API_URL = "https://aihot.virxact.com/api/public/items?mode=selected&take=60"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
W = 1086

CAT_COLORS = {
    "industry":     ("#6B46C1", "#F3F0FF", "行业动态"),
    "ai-products":  ("#10B981", "#ECFDF5", "产品发布/更新"),
    "paper":        ("#3B82F6", "#EFF6FF", "论文研究"),
    "tip":          ("#F59E0B", "#FFFBEB", "技巧与观点"),
}
CAT_ICONS = {"industry": "🏢", "ai-products": "🚀", "paper": "📄", "tip": "💡"}
CAT_NAMES = {"industry": "行业动态", "ai-products": "产品发布/更新", "paper": "论文研究", "tip": "技巧与观点"}


# ── 跨平台字体 ──────────────────────────────────────────
def _find_font_paths():
    """返回当前平台可用的中文字体路径列表。"""
    if sys.platform == "win32":
        return [
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/msyhbd.ttc",
            "C:/Windows/Fonts/simhei.ttf",
            "C:/Windows/Fonts/simsun.ttc",
        ]
    # Linux (GitHub Actions)
    return [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
    ]

FONT_PATHS = _find_font_paths()


def get_font(size, bold=False):
    for fp in FONT_PATHS:
        if os.path.exists(fp):
            try:
                if bold:
                    for bf in FONT_PATHS:
                        if ("bold" in bf.lower() or "bd" in bf.lower()) and os.path.exists(bf):
                            return ImageFont.truetype(bf, size)
                    return ImageFont.truetype(fp, size)
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
    return ImageFont.load_default()


# ── 1. 抓取新闻 ─────────────────────────────────────────
def fetch_news():
    """从 AI HOT API 获取当日精选 AI 新闻。"""
    try:
        resp = requests.get(API_URL, headers={"User-Agent": UA}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data.get("items") or data.get("data") or []
    except Exception as e:
        print(f"[ERROR] 获取新闻失败: {e}", file=sys.stderr)
        return None


def classify_news(articles):
    """按类别分桶，优先使用 API 返回的 category，否则基于关键词匹配。"""
    buckets = {k: [] for k in CAT_COLORS}
    api_cat_map = {
        "ai-models": "ai-products", "ai-products": "ai-products",
        "industry": "industry", "paper": "paper", "tip": "tip",
    }
    keywords = {
        "industry": ["融资","收购","财报","营收","估值","IPO","裁员","招聘","政策","监管",
                     "洞","趋势","报告","预测","支出","成本","CEO","黄仁勋","英伟达"],
        "ai-products": ["发布","更新","上线","开源","模型","API","产品","工具","框架",
                        "Claude","GPT","Gemini","DeepSeek","Llama","Agent","MCP",
                        "降价","版本","升级"],
        "paper": ["论文","研究","测试","实验","基准","benchmark","图灵","token",
                  "扩散","生成","推理","训练","架构"],
        "tip": ["技巧","教程","经验","实践","方法","工作流","配置","prompt",
                "编程","开发","代码","最佳实践","效率"],
    }
    for art in articles:
        api_cat = art.get("category")
        if api_cat and api_cat in api_cat_map:
            buckets[api_cat_map[api_cat]].append(art)
            continue
        title = (art.get("title") or art.get("title_en") or "").lower()
        summary = (art.get("summary") or "").lower()
        text = title + " " + summary
        best_cat = "tip"
        best_score = 0
        for cat, kws in keywords.items():
            score = sum(1 for kw in kws if kw.lower() in text)
            if score > best_score:
                best_score = score
                best_cat = cat
        buckets[best_cat].append(art)
    return buckets


def select_top(buckets, counts=None):
    """从每个分类中选取 top-N 条，并分配序号。"""
    if counts is None:
        counts = {"industry": 5, "ai-products": 5, "paper": 2, "tip": 3}
    result = {}
    idx = 1
    for cat in ["industry", "ai-products", "paper", "tip"]:
        items = buckets.get(cat, [])[:counts.get(cat, 3)]
        for art in items:
            art["id"] = idx
            art["title"] = art.get("title") or art.get("title_en") or "无标题"
            art["summary"] = art.get("summary") or ""
            idx += 1
        result[cat] = items
    return result


# ── 2. 图片生成 ─────────────────────────────────────────
def create_texture(width, height):
    base = Image.new("RGB", (width, height), "#FFFFFF")
    draw = ImageDraw.Draw(base)
    for i in range(0, width, 40):
        draw.line([(i, 0), (i, height)], fill="#F8F9FA", width=1)
    for j in range(0, height, 40):
        draw.line([(0, j), (width, j)], fill="#F8F9FA", width=1)
    for _ in range(40):
        x = random.randint(0, width)
        y = random.randint(0, height)
        r = random.randint(1, 3)
        color = random.choice(["#E0F2FE", "#FEF3C7", "#FCE7F3"])
        draw.ellipse([x - r, y - r, x + r, y + r], fill=color)
    return base.filter(ImageFilter.GaussianBlur(radius=0.5))


def generate_image(selected, date_str):
    H = 3500
    img = create_texture(W, H)
    draw = ImageDraw.Draw(img)
    y = 60
    draw.text((W // 2, y), date_str, fill="#3B82F6",
              font=get_font(64, bold=True), anchor="mm")
    y += 90
    draw.text((W // 2, y), "AI圈日报", fill="#1A1A2E",
              font=get_font(72, bold=True), anchor="mm")
    y += 100
    total = sum(len(v) for v in selected.values())
    draw.text((W // 2, y), f"{total}条 AI 重要动态速览", fill="#6B7280",
              font=get_font(32), anchor="mm")
    y += 120
    margin = 60
    content_w = W - 2 * margin

    for cat_key in ["industry", "ai-products", "paper", "tip"]:
        color, bg_color, label = CAT_COLORS[cat_key]
        items = selected[cat_key]
        if not items:
            continue
        cat_h = 52
        draw.rounded_rectangle(
            [margin, y, margin + content_w, y + cat_h], radius=8, fill=bg_color)
        draw.text((margin + 16, y + 10), CAT_ICONS[cat_key],
                  fill=color, font=get_font(28))
        draw.text((margin + 56, y + 10), f"{label}  {len(items)}条",
                  fill=color, font=get_font(24, bold=True))
        y += cat_h + 20

        for item in items:
            item_id = item["id"]
            title = item["title"]
            summary = item["summary"]
            badge_size = 40
            draw.rounded_rectangle(
                [margin, y + 4, margin + badge_size, y + 4 + badge_size],
                radius=8, fill=color)
            num_text = str(item_id)
            num_font = get_font(22, bold=True)
            bbox = draw.textbbox((0, 0), num_text, font=num_font)
            num_w = bbox[2] - bbox[0]
            num_h = bbox[3] - bbox[1]
            draw.text(
                (margin + (badge_size - num_w) // 2,
                 y + 4 + (badge_size - num_h) // 2 - 2),
                num_text, fill="white", font=num_font)
            title_x = margin + badge_size + 20
            title_font = get_font(24, bold=True)
            for i, line in enumerate(textwrap.wrap(title, width=20)[:2]):
                draw.text((title_x, y + i * 30), line, fill="#1A1A2E", font=title_font)
            y += 30 * min(len(textwrap.wrap(title, width=20)), 2)
            sum_font = get_font(20)
            for i, line in enumerate(textwrap.wrap(summary, width=36)[:2]):
                draw.text((title_x, y + i * 28), line, fill="#6B7280", font=sum_font)
            y += 28 * min(len(textwrap.wrap(summary, width=36)), 2)
            y += 15
            draw.line([(title_x, y), (margin + content_w, y)], fill="#E5E7EB", width=1)
            y += 25

    signal_bg = "#EFF6FF"
    signal_h = 180
    draw.rounded_rectangle(
        [margin, y, margin + content_w, y + signal_h], radius=12, fill=signal_bg)
    draw.text((margin + 20, y + 20), "📡 今日信号",
              fill="#3B82F6", font=get_font(28, bold=True))
    signals = _generate_signals(selected)
    for i, s in enumerate(signals[:3]):
        draw.text((margin + 40, y + 60 + i * 40), f"• {s}",
                  fill="#374151", font=get_font(22))
    y += signal_h + 40

    img = img.crop((0, 0, W, y))
    return img


def _generate_signals(selected):
    """基于真实文章数据生成今日信号摘要。"""
    signals = []
    all_titles = []
    for cat_key in ["industry", "ai-products", "paper", "tip"]:
        for item in selected.get(cat_key, []):
            all_titles.append(item["title"])

    titles_text = " ".join(all_titles)

    if any(kw in titles_text for kw in ["Agent", "MCP", "工具", "自动化", "工作流"]):
        signals.append("Agent 和自动化工具生态持续扩展，开发范式加速演变")
    if any(kw in titles_text for kw in ["NVIDIA", "英伟达", "GPU", "芯片", "Blackwell"]):
        signals.append("芯片与算力领域竞争加剧，硬件军备竞赛持续升温")
    if any(kw in titles_text for kw in ["模型", "发布", "开源", "LLM", "GPT", "Claude", "Gemini"]):
        signals.append("大模型竞争白热化，新模型与能力发布节奏加快")
    if any(kw in titles_text for kw in ["融资", "收购", "投资", "IPO", "财报"]):
        signals.append("AI 投融资持续活跃，行业整合加速推进")
    if any(kw in titles_text for kw in ["推理", "训练", "成本", "优化"]):
        signals.append("推理成本与训练效率成为技术竞争的核心焦点")

    # 确保至少有3条
    fallback = [
        "AI 技术正从互联网工具走向工业基础设施",
        "Agent 工具链加速向开发工作流渗透",
        "推理成本结构正被上下文与 Agent 任务重塑",
    ]
    while len(signals) < 3:
        for fb in fallback:
            if fb not in signals:
                signals.append(fb)
                break
    return signals[:3]


# ── 3. 文案生成 ─────────────────────────────────────────
def detect_themes(all_titles):
    """基于文章标题关键词自动检测今日主题，返回 (主题标题, 主题描述) 列表。"""
    titles_text = " ".join(all_titles)
    themes = []

    patterns = [
        (["NVIDIA", "英伟达", "GPU", "Blackwell", "芯片", "算力", "处理器"],
         "芯片与算力：军备竞赛加速",
         "今日芯片/算力领域的消息密集，NVIDIA 和各大芯片厂商动作频繁。"
         "算力军备竞赛仍是 AI 基础设施层的主旋律，硬件迭代速度远超预期。"),

        (["Agent", "MCP", "工具链", "自动化", "Workflow", "工作流", "插件"],
         "Agent 生态：工具链全面渗透",
         "Agent 和自动化工具生态持续扩展，从开发框架到部署平台再到开放标准，"
         "Agent 正在重塑软件开发和日常工作流的范式。"),

        (["开源", "开源模型", "发布", "上线", "推出"],
         "模型与产品：发布潮持续",
         "今天有多款新产品和模型发布/更新。各大厂商的迭代速度说明 AI 产品层的竞争"
         "已经从「有没有」进入到「好不好用」的阶段。"),

        (["融资", "收购", "投资", "IPO", "估值", "财报", "营收"],
         "资本动向：热钱持续涌入",
         "AI 领域的资本活动仍然活跃，大额投资和收购案层出不穷。"
         "资本对 AI 的押注没有任何降温迹象。"),

        (["推理", "训练", "架构", "优化", "成本", "效率"],
         "技术演进：推理效率成焦点",
         "AI 推理和训练技术持续演进，成本优化和架构创新是今天技术类的主题。"
         "如何让 AI 更便宜地运行，正在成为比「造更大的模型」更重要的课题。"),

        (["特斯拉", "自动驾驶", "FSD", "机器人", "具身", "硬件"],
         "具身智能与自动驾驶：落地加速",
         "自动驾驶和具身智能领域今天有重要进展。AI 能力正从纯数字世界向物理世界"
         "延伸，落地场景越来越具体。"),

        (["政策", "监管", "法规", "安全", "伦理"],
         "政策与治理：规则正在成型",
         "围绕 AI 的政策讨论和监管框架正在加速成型，各国对 AI 治理的重视程度"
         "持续提升。合规将成为 AI 企业的必修课。"),
    ]

    for keywords, title, desc in patterns:
        if any(kw.lower() in titles_text.lower() for kw in keywords):
            themes.append((title, desc))

    if not themes:
        themes.append((
            "AI 生态：全面活跃的一天",
            "今天 AI 圈涵盖了模型、产品、资本等多个维度的动态，"
            "没有单一主题主导，说明整个行业处于全面活跃期。"
        ))

    return themes[:5]


def generate_article(selected, date_str):
    """基于从 AI HOT 获取的真实文章数据，生成完整的日报分析文案。

    返回的字符串使用真实换行符，可直接用于飞书文本消息推送。
    """
    total = sum(len(v) for v in selected.values())
    lines = [
        f"# {date_str.replace('.', '')} AI圈日报",
        "",
        f"今天 AI 圈共 {total} 条重点动态，来自 AI HOT (aihot.virxact.com) 的真实精选内容。",
        "以下是分类梳理和深度分析。",
        "",
    ]

    # ── 分类逐条展示（基于真实 API 数据） ──
    for cat_key in ["industry", "ai-products", "paper", "tip"]:
        items = selected.get(cat_key, [])
        if not items:
            continue
        lines.append(f"## {CAT_ICONS[cat_key]} {CAT_NAMES[cat_key]}（{len(items)}条）")
        lines.append("")
        for item in items:
            title = item["title"]
            summary = item.get("summary", "")
            source = item.get("source", "")
            url = item.get("url", "")
            lines.append(f"**{item['id']}. {title}**")
            if summary:
                lines.append(f"> {summary}")
            if source:
                source_line = f"  来源：{source}"
                if url:
                    source_line += f"（{url}）"
                lines.append(source_line)
            lines.append("")
        lines.append("")

    # ── 动态趋势分析（基于文章关键词自动检测） ──
    all_titles = []
    for cat_key in ["industry", "ai-products", "paper", "tip"]:
        for item in selected.get(cat_key, []):
            all_titles.append(item["title"])

    themes = detect_themes(all_titles)

    lines.append("## 📡 今日深度观察")
    lines.append("")
    lines.append("基于以上真实资讯，今天 AI 圈有几个值得关注的趋势：")
    lines.append("")

    for idx, (theme_title, theme_desc) in enumerate(themes, 1):
        lines.append(f"### {idx}. {theme_title}")
        lines.append(theme_desc)
        lines.append("")

    # ── 总结 ──
    lines.append("---")
    lines.append("")
    lines.append("### 写在最后")
    lines.append("")
    lines.append(
        "以上内容全部来自 AI HOT 当日精选的 AI 行业资讯，"
        "涵盖行业动态、产品发布、论文研究和技术观点。"
    )
    lines.append("")
    lines.append(
        "追 AI 新闻不是为了焦虑，而是为了理解这个领域的变化方向和节奏。"
        "看懂趋势比追每一个模型更重要。"
    )
    lines.append("")
    lines.append("#AI日报 #人工智能 #AI工具 #Agent #大模型")

    # 使用真实换行符拼接，不是字面字符串 "\\n"
    return "\n".join(lines)


# ── 4. 飞书推送 ─────────────────────────────────────────
def get_tenant_token(app_id, app_secret):
    resp = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"获取 Token 失败: {data}")
    return data["tenant_access_token"]


def upload_image(token, image_bytes):
    """上传图片到飞书，返回 image_key。"""
    resp = requests.post(
        "https://open.feishu.cn/open-apis/im/v1/images",
        headers={"Authorization": f"Bearer {token}"},
        files={"image_type": (None, "message"),
               "image": ("ai_daily.png", BytesIO(image_bytes), "image/png")},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"上传图片失败: {data}")
    return data["data"]["image_key"]


def send_image_message(token, chat_id, image_key):
    resp = requests.post(
        "https://open.feishu.cn/open-apis/im/v1/messages",
        params={"receive_id_type": "chat_id"},
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
        json={
            "receive_id": chat_id,
            "msg_type": "image",
            "content": json.dumps({"image_key": image_key}),
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"发送图片失败: {data}")
    return data["data"]["message_id"]


def send_text_message(token, chat_id, text):
    resp = requests.post(
        "https://open.feishu.cn/open-apis/im/v1/messages",
        params={"receive_id_type": "chat_id"},
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
        json={
            "receive_id": chat_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}),
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"发送文本失败: {data}")
    return data["data"]["message_id"]


# ── 主流程 ──────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="AI日报全流程生成+推送")
    parser.add_argument("--output-dir", default="output",
                        help="产物输出目录（默认 output）")
    parser.add_argument("--app-id", default=None,
                        help="飞书 App ID（可从环境变量 FEISHU_APP_ID 读取）")
    parser.add_argument("--app-secret", default=None,
                        help="飞书 App Secret（可从环境变量 FEISHU_APP_SECRET 读取）")
    parser.add_argument("--chat-id", default=None,
                        help="飞书群 Chat ID（可从环境变量 FEISHU_CHAT_ID 读取）")
    parser.add_argument("--skip-push", action="store_true",
                        help="仅生成不推送")
    args = parser.parse_args()

    # 凭据：命令行 > 环境变量
    app_id = args.app_id or os.environ.get("FEISHU_APP_ID")
    app_secret = args.app_secret or os.environ.get("FEISHU_APP_SECRET")
    chat_id = args.chat_id or os.environ.get("FEISHU_CHAT_ID")

    # GitHub Actions 会注入这些凭据，缺失时仅本地生成
    if not args.skip_push and (not app_id or not app_secret or not chat_id):
        print("[WARN] 缺少飞书凭据，仅本地生成，跳过推送。")
        args.skip_push = True

    # 日期
    now = datetime.now()
    date_str = now.strftime("%Y.%m.%d")
    date_compact = now.strftime("%Y%m%d")

    # 创建输出目录
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. 抓取 & 分类 & 精选
    print("[1/5] 从 AI HOT 抓取资讯...")
    articles = fetch_news()
    if not articles:
        print("[ERROR] 无法获取新闻数据，退出。", file=sys.stderr)
        sys.exit(1)
    print(f"  获取到 {len(articles)} 篇文章")

    buckets = classify_news(articles)
    selected = select_top(buckets)
    total = sum(len(v) for v in selected.values())
    print(f"  精选 {total} 条: industry={len(selected['industry'])} "
          f"products={len(selected['ai-products'])} "
          f"paper={len(selected['paper'])} tip={len(selected['tip'])}")

    # 2. 生成长图
    print("[2/5] 生成日报长图...")
    img = generate_image(selected, date_str)

    # 3. 保存图片
    img_path = out_dir / f"ai_daily_{date_compact}.png"
    img.save(img_path, "PNG")
    print(f"  图片: {img_path}")

    # 4. 生成文案
    print("[3/5] 生成分析文案...")
    article = generate_article(selected, date_str)
    md_path = out_dir / f"AI日报_{date_compact}.md"
    md_path.write_text(article, encoding="utf-8")
    print(f"  文案: {md_path}")

    # 5. 推送飞书
    if args.skip_push:
        print("[4/5] 跳过推送")
    else:
        print("[4/5] 推送到飞书群...")
        try:
            token = get_tenant_token(app_id, app_secret)
            # 图片转 bytes
            buf = BytesIO()
            img.save(buf, format="PNG")
            buf.seek(0)
            image_key = upload_image(token, buf.getvalue())
            msg_id_img = send_image_message(token, chat_id, image_key)
            print(f"  图片消息已发送: {msg_id_img}")
            # 发送完整分析文案（generate_article 已使用真实换行符）
            article_text = article
            if len(article_text) > 30000:
                article_text = article_text[:30000] + "\n\n...(完整文案见 Markdown 文件)"
            msg_id_txt = send_text_message(token, chat_id, article_text)
            print(f"  分析文案已发送: {msg_id_txt}")
        except Exception as e:
            print(f"[ERROR] 推送失败: {e}", file=sys.stderr)
            sys.exit(1)

    # 6. 打印摘要
    print("\n=== 精选摘要 ===")
    all_items = []
    for cat_key in ["industry", "ai-products", "paper", "tip"]:
        for item in selected.get(cat_key, []):
            all_items.append((item["id"], CAT_COLORS[cat_key][2], item["title"]))
    for sid, cat_label, title in all_items:
        print(f"  [{sid}] [{cat_label}] {title}")

    print("\n[DONE] AI日报全流程完成！")


if __name__ == "__main__":
    main()