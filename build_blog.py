import os
import shutil
import frontmatter
import markdown
from jinja2 import Environment, FileSystemLoader

POSTS_DIR = "blog_posts"
OUTPUT_DIR = "landing/blog"
SITEMAP_PATH = "landing/sitemap.xml"

# Setup Jinja2 environment
env = Environment(loader=FileSystemLoader("."))

def generate_sitemap(posts):
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
    
    # Load Jinja2 templates
    post_template = env.get_template("blog_template.html")
    index_template = env.get_template("blog_index_template.html")

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
        
        # Render post template
        final_html = post_template.render(
            title=post.get("title", "Untitled"),
            date=post.get("date", ""),
            summary=post.get("summary", ""),
            canonical=post.get("canonical", f"https://agenttrafficcop.com/blog/{slug}"),
            content=html_content
        )
        
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

    # Render index template
    final_index = index_template.render(posts=posts)
    with open(os.path.join(OUTPUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(final_index)

    # RSS Feed
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
        
    generate_sitemap(posts)
    print(f"Successfully built {len(posts)} blog posts, index, and RSS feed.")

if __name__ == "__main__":
    build()