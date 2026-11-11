# External solution sources and attribution

The on-demand multilingual lookup currently uses:

- **Doocs/leetcode** — https://github.com/doocs/leetcode
- License: **Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)**
- The downloader stores the upstream source URL and license in `solutions_db/_master_index.json` and adds source/license comments to each downloaded solution file.

Doocs is a community-maintained third-party repository and is not affiliated with LeetCode. Its code is treated as an untrusted candidate: the automation must run syntax checks and LeetCode sample validation before any submission. A source match is not evidence that a solution is accepted.

The downloader fetches only the requested problem and language at runtime rather than cloning the entire upstream repository. If the source is unavailable or does not contain that language, the pipeline proceeds to Gemini.
