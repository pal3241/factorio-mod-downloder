# Changelog

## 2.2.0

- Fixed Search Mods HTTP 403 in no-login mode.
- Replaced authenticated `POST /api/search` usage with public Mod Portal browse/search pages plus public per-mod metadata.
- Preserved query, sort, filters, exclusions, and pagination without username/token.
- Added bounded concurrent metadata enrichment for the visible page.
- Excluded `Internal` by default and reduced Search UI contrast in Flet and Web modes.
- Added an offline regression test that rejects any `POST /api/search` call.

## 2.1.0

- Rebuilt Discover into a Factorio Mod Portal-style Search Mods tab.
- Added Highlighted, Recently updated, Most downloaded, Trending, and Search modes.
- Added include/exclude filtering for Space Age, categories, and tags.
- Added pagination and accurate search result counts from the portal search response.
- Added thumbnail, author, summary, category, compatibility, download count, tags, installed/update state, and one-click install/update.
- Added the same search workflow to both Flask Web and Flet Desktop/Web.
- Added offline tests for search payload sanitization and result enrichment.
