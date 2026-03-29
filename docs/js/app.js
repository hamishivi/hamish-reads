/**
 * AI Research Digest — frontend logic
 * Handles tab switching, date navigation, and data rendering.
 */

(function () {
    "use strict";

    const DATA_BASE = "data";
    let availableDates = [];
    let currentDateIndex = 0;

    // --- DOM refs ---
    const dateDisplay = document.getElementById("date-display");
    const datePicker = document.getElementById("date-picker");
    const prevBtn = document.getElementById("prev-day");
    const nextBtn = document.getElementById("next-day");
    const tabs = document.querySelectorAll(".tab");
    const tabContents = document.querySelectorAll(".tab-content");

    // --- Init ---
    async function init() {
        setupTabs();
        setupDatePicker();
        await loadDates();
    }

    // --- Tabs ---
    function setupTabs() {
        tabs.forEach((tab) => {
            tab.addEventListener("click", () => {
                tabs.forEach((t) => t.classList.remove("active"));
                tabContents.forEach((tc) => tc.classList.remove("active"));
                tab.classList.add("active");
                const target = document.getElementById(tab.dataset.tab + "-tab");
                if (target) target.classList.add("active");
            });
        });
    }

    // --- Date navigation ---
    function setupDatePicker() {
        dateDisplay.addEventListener("click", () => {
            datePicker.showPicker?.() || datePicker.click();
        });

        datePicker.addEventListener("change", () => {
            const val = datePicker.value;
            const idx = availableDates.indexOf(val);
            if (idx >= 0) {
                currentDateIndex = idx;
                loadDay(availableDates[currentDateIndex]);
            }
        });

        prevBtn.addEventListener("click", () => {
            if (currentDateIndex < availableDates.length - 1) {
                currentDateIndex++;
                loadDay(availableDates[currentDateIndex]);
            }
        });

        nextBtn.addEventListener("click", () => {
            if (currentDateIndex > 0) {
                currentDateIndex--;
                loadDay(availableDates[currentDateIndex]);
            }
        });
    }

    function updateNavButtons() {
        prevBtn.disabled = currentDateIndex >= availableDates.length - 1;
        nextBtn.disabled = currentDateIndex <= 0;
    }

    function formatDate(dateStr) {
        const d = new Date(dateStr + "T12:00:00");
        return d.toLocaleDateString("en-US", {
            weekday: "short",
            month: "short",
            day: "numeric",
            year: "numeric",
        });
    }

    // --- Data loading ---
    async function loadDates() {
        try {
            const resp = await fetch(`${DATA_BASE}/dates.json`);
            availableDates = await resp.json();
            if (availableDates.length > 0) {
                currentDateIndex = 0;
                loadDay(availableDates[0]);
            } else {
                showEmpty();
            }
        } catch (e) {
            showEmpty();
        }
    }

    async function loadDay(dateStr) {
        dateDisplay.textContent = formatDate(dateStr);
        datePicker.value = dateStr;
        updateNavButtons();

        // Load papers, tweets, news, and cost in parallel
        const [papers, tweets, news, cost] = await Promise.all([
            fetchJSON(`${DATA_BASE}/${dateStr}/papers.json`),
            fetchJSON(`${DATA_BASE}/${dateStr}/tweets.json`),
            fetchJSON(`${DATA_BASE}/${dateStr}/news.json`),
            fetchJSON(`${DATA_BASE}/${dateStr}/cost.json`),
        ]);

        renderPapers(papers);
        renderTweets(tweets);
        renderNews(news);
        renderFooter(papers, tweets, cost);
    }

    async function fetchJSON(url) {
        try {
            const resp = await fetch(url);
            if (!resp.ok) return null;
            return await resp.json();
        } catch {
            return null;
        }
    }

    function showEmpty() {
        dateDisplay.textContent = "No data yet";
        document.getElementById("author-papers-empty").style.display = "block";
        document.getElementById("ranked-papers-empty").style.display = "block";
        document.getElementById("tweets-empty").style.display = "block";
    }

    // --- Render papers ---
    function renderPapers(data) {
        const authorList = document.getElementById("author-paper-list");
        const rankedList = document.getElementById("ranked-paper-list");
        const authorEmpty = document.getElementById("author-papers-empty");
        const rankedEmpty = document.getElementById("ranked-papers-empty");

        authorList.innerHTML = "";
        rankedList.innerHTML = "";

        if (!data) {
            authorEmpty.style.display = "block";
            rankedEmpty.style.display = "block";
            return;
        }

        const authorPapers = data.author_papers || [];
        const rankedPapers = data.ranked_papers || [];

        authorEmpty.style.display = authorPapers.length === 0 ? "block" : "none";
        rankedEmpty.style.display = rankedPapers.length === 0 ? "block" : "none";

        authorPapers.forEach((p) => authorList.appendChild(createPaperEl(p, true)));
        rankedPapers.forEach((p) => rankedList.appendChild(createPaperEl(p, false)));
    }

    function createPaperEl(paper, isAuthorMatch) {
        const li = document.createElement("li");
        li.className = "paper-item";

        // Truncate author list
        const maxAuthors = 8;
        const authorStrs = paper.authors.slice(0, maxAuthors).map((a) => {
            if (paper.is_author_match) {
                // We don't have the followed list client-side, so just render normally
                return escapeHtml(a);
            }
            return escapeHtml(a);
        });
        if (paper.authors.length > maxAuthors) {
            authorStrs.push(`<em>et al.</em>`);
        }

        let badges = "";
        if (!isAuthorMatch && paper.relevance_score > 0) {
            badges += `<span class="badge badge-score">${paper.relevance_score.toFixed(1)}/10</span>`;
        }
        paper.categories.slice(0, 3).forEach((cat) => {
            badges += `<span class="badge badge-category">${escapeHtml(cat)}</span>`;
        });

        let reason = "";
        if (paper.relevance_reason) {
            reason = `<p class="paper-reason">${escapeHtml(paper.relevance_reason)}</p>`;
        }

        li.innerHTML = `
            <div class="paper-title"><a href="${escapeHtml(paper.abs_url)}" target="_blank" rel="noopener">${escapeHtml(paper.title)}</a></div>
            <div class="paper-meta">${authorStrs.join(", ")}</div>
            <div class="paper-badges">${badges}</div>
            ${reason}
            <details class="paper-abstract">
                <summary>Abstract</summary>
                <p>${escapeHtml(paper.abstract)}</p>
            </details>
            <div class="paper-links">
                <a href="${escapeHtml(paper.abs_url)}" target="_blank" rel="noopener">arxiv</a>
                <a href="${escapeHtml(paper.pdf_url)}" target="_blank" rel="noopener">pdf</a>
            </div>
        `;
        return li;
    }

    // --- Render tweets ---
    function renderTweets(data) {
        const threadsList = document.getElementById("paper-threads-list");
        const announcementsList = document.getElementById("announcements-list");
        const discussionsList = document.getElementById("discussions-list");
        const tweetsEmpty = document.getElementById("tweets-empty");

        threadsList.innerHTML = "";
        announcementsList.innerHTML = "";
        discussionsList.innerHTML = "";

        if (!data) {
            tweetsEmpty.style.display = "block";
            return;
        }

        const threads = data.paper_threads || [];
        const announcements = data.announcements || [];
        const discussions = data.discussions || [];

        const hasAny = threads.length + announcements.length + discussions.length > 0;
        tweetsEmpty.style.display = hasAny ? "none" : "block";

        threads.forEach((t) => threadsList.appendChild(createTweetEl(t)));
        announcements.forEach((t) => announcementsList.appendChild(createTweetEl(t)));
        discussions.forEach((t) => discussionsList.appendChild(createTweetEl(t)));

        if (hasAny) loadTwitterEmbeds();
    }

    function createTweetEl(tweet) {
        const li = document.createElement("li");
        li.className = "tweet-item";

        // Summary line above the embed
        const summary = document.createElement("p");
        summary.className = "tweet-summary";
        summary.textContent = tweet.summary;
        li.appendChild(summary);

        // Extract tweet ID from URL for iframe embed
        const tweetId = extractTweetId(tweet.tweet_url);
        if (tweetId) {
            // Use iframe embed — more reliable than blockquote + widgets.js
            const wrapper = document.createElement("div");
            wrapper.className = "tweet-embed-wrapper";
            wrapper.innerHTML = `<blockquote class="twitter-tweet" data-conversation="none" data-dnt="true"><a href="${escapeHtml(tweet.tweet_url)}"></a></blockquote>`;
            li.appendChild(wrapper);
        } else {
            // Fallback: just link to the tweet
            const meta = document.createElement("div");
            meta.className = "tweet-meta";
            const author = tweet.author_username ? `@${escapeHtml(tweet.author_username)} · ` : "";
            meta.innerHTML = `${author}<a href="${escapeHtml(tweet.tweet_url)}" target="_blank" rel="noopener">View tweet &rarr;</a>`;
            li.appendChild(meta);
        }

        return li;
    }

    function extractTweetId(url) {
        if (!url) return null;
        const match = url.match(/(?:twitter\.com|x\.com)\/\w+\/status\/(\d+)/);
        return match ? match[1] : null;
    }

    /** Load Twitter widgets.js and render embeds */
    let twitterScriptLoaded = false;
    function loadTwitterEmbeds() {
        if (window.twttr && window.twttr.widgets) {
            // Script already loaded — just re-render new blockquotes
            window.twttr.widgets.load(document.getElementById("tweets-tab"));
            return;
        }
        if (twitterScriptLoaded) return;
        twitterScriptLoaded = true;

        // Set up the twttr ready callback before loading the script
        window.twttr = window.twttr || {};
        window.twttr._e = window.twttr._e || [];
        window.twttr.ready = function (fn) {
            window.twttr._e.push(fn);
        };
        window.twttr.ready(function (twttr) {
            twttr.widgets.load(document.getElementById("tweets-tab"));
        });

        const script = document.createElement("script");
        script.src = "https://platform.twitter.com/widgets.js";
        script.async = true;
        script.charset = "utf-8";
        document.head.appendChild(script);
    }

    // --- Render news ---
    function renderNews(data) {
        const grid = document.getElementById("news-grid");
        const newsEmpty = document.getElementById("news-empty");
        grid.innerHTML = "";

        if (!data || !data.publications || data.publications.length === 0) {
            newsEmpty.style.display = "block";
            return;
        }

        newsEmpty.style.display = "none";

        data.publications.forEach((pub) => {
            const card = document.createElement("div");
            card.className = "news-card";

            let articlesHtml = "";
            if (pub.articles && pub.articles.length > 0) {
                const items = pub.articles
                    .map(
                        (a) =>
                            `<li><a href="${escapeHtml(a.url)}" target="_blank" rel="noopener">${escapeHtml(a.title)}</a></li>`
                    )
                    .join("");
                articlesHtml = `<ul class="news-card-articles">${items}</ul>`;
            }

            card.innerHTML = `
                <div class="news-card-header">
                    <img src="${escapeHtml(pub.logo_url)}" alt="" loading="lazy">
                    <a href="${escapeHtml(pub.url)}" target="_blank" rel="noopener">${escapeHtml(pub.name)}</a>
                </div>
                ${articlesHtml}
            `;
            grid.appendChild(card);
        });
    }

    // --- Footer ---
    function renderFooter(papers, tweets, cost) {
        const footer = document.getElementById("generated-at");
        const parts = [];

        const genAt = papers?.generated_at || tweets?.generated_at || "";
        if (genAt) {
            parts.push("Generated " + new Date(genAt).toLocaleString());
        }

        if (cost) {
            const costParts = [];
            if (cost.claude) {
                costParts.push(`Claude $${cost.claude.estimated_cost_usd.toFixed(4)}`);
            }
            if (cost.twitter) {
                costParts.push(`Twitter $${cost.twitter.estimated_cost_usd.toFixed(4)}`);
            }
            parts.push(`Today's cost: $${cost.total_estimated_cost_usd.toFixed(4)} (${costParts.join(" + ")})`);
        }

        footer.innerHTML = parts.join("<br>");

        // Also load cumulative cost
        fetchJSON(`${DATA_BASE}/cost_log.json`).then((log) => {
            if (log && log.total_cost_usd > 0) {
                const cumulative = document.createElement("span");
                cumulative.className = "cumulative-cost";
                cumulative.textContent = ` · All-time: $${log.total_cost_usd.toFixed(4)} over ${log.days.length} days`;
                footer.appendChild(cumulative);
            }
        });
    }

    // --- Util ---
    function escapeHtml(str) {
        if (!str) return "";
        const div = document.createElement("div");
        div.textContent = str;
        return div.innerHTML;
    }

    // --- Start ---
    init();
})();
