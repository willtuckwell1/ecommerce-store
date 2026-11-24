"""Fetch recent posts from a public Reddit subreddit."""

import requests


def get_reddit_posts(subreddit="python"):
    """Return a list of Reddit post dictionaries for the template."""
    # Build the request URL for the chosen subreddit.
    url = f"https://www.reddit.com/r/{subreddit}/.json"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        )
    }

    # Send the request to Reddit with a user-agent header.
    response = requests.get(url, headers=headers, timeout=10)

    # Handle failed requests cleanly.
    if response.status_code != 200:
        return {"error": f"Failed to fetch data: {response.status_code}"}

    # Parse the JSON response and extract the first few posts.
    data = response.json()
    posts = []

    for item in data.get("data", {}).get("children", [])[:5]:
        post = item.get("data", {})
        permalink = post.get("permalink", "")
        posts.append(
            {
                "title": post.get("title", "Untitled"),
                "author": post.get("author", "unknown"),
                "url": f"https://www.reddit.com{permalink}",
            }
        )

    return posts