"""
2567. Minimum Score by Changing Two Elements
Difficulty: Medium
Runtime: 32 ms
Memory: 31.4 MB
Solved: 2026-11-19T07:50:04.459155+00:00
"""

class Solution:
  def minimizeSum(self, nums: list[int]) -> int:
    nums.sort()
    # Can always change the number to any other number in `nums`, so `low` becomes 0.
    # Thus, rephrase the problem as finding the minimum `high`.
    highOfChangingTwoMins = nums[-1] - nums[2]
    highOfChangingTwoMaxs = nums[-3] - nums[0]
    highOfChangingMinAndMax = nums[-2] - nums[1]
    return min(highOfChangingTwoMins, highOfChangingTwoMaxs,
               highOfChangingMinAndMax)
