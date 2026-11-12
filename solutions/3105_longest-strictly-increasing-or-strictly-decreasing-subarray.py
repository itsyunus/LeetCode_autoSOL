"""
3105. Longest Strictly Increasing or Strictly Decreasing Subarray
Difficulty: Easy
Runtime: 2 ms
Memory: 19 MB
Solved: 2026-11-12T02:58:00.123004+00:00
"""

class Solution:
  # Similar to 978. Longest Turbulent Subarray
  def longestMonotonicSubarray(self, nums: list[int]) -> int:
    ans = 1
    increasing = 1
    decreasing = 1

    for i in range(1, len(nums)):
      if nums[i] > nums[i - 1]:
        increasing += 1
        decreasing = 1
      elif nums[i] < nums[i - 1]:
        decreasing += 1
        increasing = 1
      else:
        increasing = 1
        decreasing = 1
      ans = max(ans, increasing, decreasing)

    return ans
