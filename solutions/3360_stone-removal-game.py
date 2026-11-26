"""
3360. Stone Removal Game
Difficulty: Easy
Runtime: 0 ms
Memory: 19.1 MB
Solved: 2026-11-26T08:51:57.684603+00:00
"""

class Solution:
  def canAliceWin(self, n: int) -> bool:
    for stones in range(10, -1, -1):
      if stones > n:
        return stones % 2 == 1
      n -= stones
