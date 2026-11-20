"""
3041. Maximize Consecutive Elements in an Array After Modification
Difficulty: Hard
Runtime: 244 ms
Memory: 43.1 MB
Solved: 2026-11-20T07:42:48.094329+00:00
"""

class Solution:
  def maxSelectedElements(self, nums: list[int]) -> int:
    ans = 0
    # {num: the length of the longest consecutive elements ending in num}
    dp = {}

    for num in sorted(nums):
      dp[num + 1] = dp.get(num, 0) + 1
      dp[num] = dp.get(num - 1, 0) + 1
      ans = max(ans, dp[num], dp[num + 1])

    return ans
