# Apify fixture provenance

`apify_instagram_post_sample.json` and `apify_instagram_profile_sample.json`
are minimal outputs from successful one-result live runs on 2026-11-02 for the
public `natgeo` profile. Apify run IDs were `UGgbQU1T1g8mbE3Yz` (post actor)
and `uXEHq9SrBfdEKcJl0` (profile actor); both reported a run cost of USD 0.00.
The runs used the official Store actors `apify/instagram-post-scraper` and
`apify/instagram-profile-scraper`.

`apify_instagram_post_detailed_docs_sample.json` is a minimal excerpt of a
Detailed data example published on the Post Scraper Store page:
<https://apify.com/apify/instagram-post-scraper> (accessed 2026-11-02). The
live run used `basicData`, so it did not return the optional video play/view
fields present in the Detailed data example.

The live fixtures preserve the fields relevant to ranking and deduplication.
These fixtures are actor-format examples and test data; they do not contain the
results of the Oskar Kuban campaign.
