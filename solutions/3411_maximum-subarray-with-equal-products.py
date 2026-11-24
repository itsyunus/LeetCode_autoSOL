"""
3411. Maximum Subarray With Equal Products
Difficulty: Easy
Runtime: 37 ms
Memory: 19.1 MB
Solved: 2026-11-24T06:11:14.530656+00:00
"""

class Solution:
  def maxLength(self, nums: list[int]) -> int:
    n = len(nums)
    ans = 0

    for i in range(n):
      prod = 1
      l = 1
      g = 0
      for j in range(i, n):
        prod *= nums[j]
        l = math.lcm(l, nums[j])
        g = math.gcd(g, nums[j])
        if prod == l * g:
          ans = max(ans, j - i + 1)

    return ans
