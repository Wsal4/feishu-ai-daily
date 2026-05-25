#!/usr/bin/env python3
"""AI 日报全流程脚本：抓取 → 生成图片/文案 → 推送飞书群。

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
    try:
        resp = requests.get(API_URL, headers={"User-Agent": UA}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data.get("items") or data.get("data") or []
    except Exception as e:
        print(f"[ERROR] 获取新闻失败: {e}", file=sys.stderr)
        return None


def classify_news(articles):
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
    signals = [
        "工业AI与物理仿真成为新热点，Mistral收购案标志行业拐点",
        "Agent工具链加速向开发工作流渗透，Google I/O全栈布局",
        "推理成本结构正被上下文与Agent任务重塑，96K token成中位",
    ]
    for i, s in enumerate(signals):
        draw.text((margin + 40, y + 60 + i * 40), f"• {s}",
                  fill="#374151", font=get_font(22))
    y += signal_h + 40

    img = img.crop((0, 0, W, y))
    return img


# ── 3. 文案生成 ─────────────────────────────────────────
def generate_article(selected, date_str):
    total = sum(len(v) for v in selected.values())
    lines = [
        f"# {date_str.replace('.', '')} AI圈日报",
        "",
        f"今天 AI 圈的 {total} 条重点动态，我整理成了一张长图。",
        "",
    ]
    all_titles = []
    for cat_key in ["industry", "ai-products", "paper", "tip"]:
        for item in selected.get(cat_key, []):
            all_titles.append(item["title"].split("：")[0].split("，")[0])
    lines.append("这一天的信息，表面看是新闻很多：" + "、".join(all_titles[:8]) + "……")
    lines.append("")
    lines.append("但如果放在一起看，背后其实有几个很明显的信号。")
    lines.append("")

    trends = [
        ("第一，**AI 正在从「互联网工具」走向「工业基础设施」**。",
         "今天最重磅的是 AI 技术在工业场景的深度渗透——物理仿真、数字孪生、智能制造。AI 不再只是生成文本和图片，而是开始处理复杂的工程问题，从消费级向工业级关键拐点迈进。"),
        ("第二，**企业用 AI 不一定天然省钱**。",
         "基于 token 和 agent 的 AI 使用模式，综合开销已可能超过人类员工费用。这打破了「AI 必然降本增效」的简单假设，推理成本结构已与早期小模型时代截然不同。"),
        ("第三，**AI 基建的投入还会继续变大**。",
         "超大规模云厂商的 AI 基建年度开支仍在指数级增长，远超外界预期。算力需求、模型训练、推理部署构成了持续膨胀的投入飞轮。"),
        ("第四，**AI 对入门级岗位的压力正在加剧**。",
         "AI 工具被广泛用于入门级任务，企业招聘重心转向高级岗位。初级岗位削减比例大幅跃升，不仅是技术替代问题，更是人才结构重塑的开始。"),
        ("第五，**Agent 正在重塑开发者工作流和推理经济学**。",
         "从开发工具链到开放标准再到托管代理服务，Agent 形成了从开发、接口到部署的完整生态。真实编码 Agent 请求的中位上下文已达近10万token。"),
    ]
    for heading, body in trends:
        lines.append(heading)
        lines.append(body)
        lines.append("")

    lines.extend([
        "整体看下来，AI 圈正在经历三个关键转变：从消费级到工业级、从降本工具到成本中心、从辅助工具到工作流核心。",
        "",
        "所以我觉得，普通人看 AI 新闻，不一定要追每一个新模型。更重要的是看懂：",
        "- 哪些变化会进入真实业务？",
        "- 哪些工具会改变工作方式？",
        "- 哪些趋势会影响职业机会？",
        "",
        "这才是每天追 AI 动态真正有价值的地方。",
        "",
        "#AI日报 #人工智能 #AI工具 #Agent #工业AI #大模型",
    ])
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
    print("[1/5] 抓取 AI HOT 资讯...")
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
            # 摘要文本
            summary_text = f"📰 {date_str} AI圈日报\n共 {total} 条精选动态，长图已推送。"
            msg_id_txt = send_text_message(token, chat_id, summary_text)
            print(f"  摘要消息已发送: {msg_id_txt}")
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