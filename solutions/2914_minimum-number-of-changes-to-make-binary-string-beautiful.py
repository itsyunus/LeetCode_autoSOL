"""
2914. Minimum Number of Changes to Make Binary String Beautiful
Difficulty: Medium
Runtime: 14 ms
Memory: 19.7 MB
Solved: 2026-11-18T07:54:02.430618+00:00
"""

class Solution:
  def minChanges(self, s: str) -> int:
    return sum(a != b for a, b in zip(s[::2], s[1::2]))
