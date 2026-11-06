import os
import frontmatter
import markdown

POSTS_DIR = "blog_posts"
OUTPUT_DIR = "landing/blog"
TEMPLATE_PATH = "blog_template.html"
INDEX_TEMPLATE_PATH = "blog_index_template.html"

def build():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    posts = []
    
    # Read templates
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        post_template = f.read()
    with open(INDEX_TEMPLATE_PATH, "r", encoding="utf-8") as f:
        index_template = f.read()

    # Parse Markdown files
    for filename in os.listdir(POSTS_DIR):
        if not filename.endswith(".md"):
            continue
            
        filepath = os.path.join(POSTS_DIR, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            post = frontmatter.load(f)
            
        slug = filename.replace(".md", "")
        
        # Convert Markdown to HTML (with code block support)
        html_content = markdown.markdown(
            post.content, 
            extensions=['fenced_code', 'codehilite', 'tables']
        )
        
        # Build the final HTML for the post
        final_html = post_template.replace("{{TITLE}}", post.get("title", "Untitled"))
        final_html = final_html.replace("{{DATE}}", post.get("date", ""))
        final_html = final_html.replace("{{SUMMARY}}", post.get("summary", ""))
        final_html = final_html.replace("{{CANONICAL}}", post.get("canonical", f"https://agenttrafficcop.com/blog/{slug}"))
        final_html = final_html.replace("{{CONTENT}}", html_content)
        
        # Create a clean URL folder (e.g., /blog/my-post/index.html)
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

    # Sort posts by date (newest first)
    posts.sort(key=lambda x: x["date"], reverse=True)

    # Generate Blog Index Page
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

    # Generate RSS Feed
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

    print(f"Successfully built {len(posts)} blog posts, index, and RSS feed.")

if __name__ == "__main__":
    build()