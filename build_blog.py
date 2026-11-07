import os
import shutil
import frontmatter
import markdown
from datetime import datetime

POSTS_DIR = "blog_posts"
OUTPUT_DIR = "landing/blog"
TEMPLATE_PATH = "blog_template.html"
INDEX_TEMPLATE_PATH = "blog_index_template.html"
SITEMAP_PATH = "landing/sitemap.xml"

def generate_sitemap(posts):
    """Generate a sitemap.xml for SEO."""
    urls = [
        "https://agenttrafficcop.com/",
        "https://agenttrafficcop.com/dashboard.html",
        "https://agenttrafficcop.com/blog/"
    ]
    
    for p in posts:
        urls.append(f"https://agenttrafficcop.com/blog/{p['slug']}/")

    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for url in urls:
        xml += f"  <url><loc>{url}</loc></url>\n"
    xml += '</urlset>\n'
    
    with open(SITEMAP_PATH, "w", encoding="utf-8") as f:
        f.write(xml)
    print(f"Successfully generated sitemap with {len(urls)} URLs.")

def build():
    if os.path.exists(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR)
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    posts = []
    
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        post_template = f.read()
    with open(INDEX_TEMPLATE_PATH, "r", encoding="utf-8") as f:
        index_template = f.read()

    for filename in os.listdir(POSTS_DIR):
        if not filename.endswith(".md"):
            continue
            
        filepath = os.path.join(POSTS_DIR, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            post = frontmatter.load(f)
            
        slug = filename.replace(".md", "")
        
        html_content = markdown.markdown(
            post.content, 
            extensions=['fenced_code', 'codehilite', 'tables']
        )
        
        final_html = post_template.replace("{{TITLE}}", post.get("title", "Untitled"))
        final_html = final_html.replace("{{DATE}}", post.get("date", ""))
        final_html = final_html.replace("{{SUMMARY}}", post.get("summary", ""))
        final_html = final_html.replace("{{CANONICAL}}", post.get("canonical", f"https://agenttrafficcop.com/blog/{slug}"))
        final_html = final_html.replace("{{CONTENT}}", html_content)
        
        post_dir = os.path.join(OUTPUT_DIR, slug)
        os.makedirs(post_dir, exist_ok=True)
        with open(os.path.join(post_dir, "index.html"), "w", encoding="utf-8") as f:
            f.write(final_html)
            
        posts.append({
            "title": post.get("title", "Untitled"),
            "date": post.get("date", ""),
            "summary": post.get("summary", ""),
            "slug": slug
        })

    posts.sort(key=lambda x: x["date"], reverse=True)

    posts_html = ""
    for p in posts:
        posts_html += f"""
        <a href="/blog/{p['slug']}" class="post-card">
            <div class="post-date">{p['date']}</div>
            <h2 class="post-title">{p['title']}</h2>
            <p class="post-summary">{p['summary']}</p>
        </a>
        """
        
    final_index = index_template.replace("{{POSTS}}", posts_html)
    with open(os.path.join(OUTPUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(final_index)

    rss_items = "".join([f"""
    <item>
        <title>{p['title']}</title>
        <link>https://agenttrafficcop.com/blog/{p['slug']}</link>
        <description>{p['summary']}</description>
        <pubDate>{p['date']}</pubDate>
    </item>""" for p in posts])
    
    rss_feed = f"""<?xml version="1.0" encoding="UTF-8" ?>
    <rss version="2.0">
    <channel>
        <title>AgentTrafficCop Blog</title>
        <link>https://agenttrafficcop.com/blog</link>
        <description>Stop AI agents from burning money in loops.</description>
        {rss_items}
    </channel>
    </rss>"""
    
    with open(os.path.join(OUTPUT_DIR, "feed.xml"), "w", encoding="utf-8") as f:
        f.write(rss_feed)
        
    # Generate the sitemap!
    generate_sitemap(posts)
    
    print(f"Successfully built {len(posts)} blog posts, index, and RSS feed.")

if __name__ == "__main__":
    build()