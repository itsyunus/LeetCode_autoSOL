"""
1524. Number of Sub-arrays With Odd Sum
Difficulty: Medium
Runtime: 84 ms
Memory: 24.6 MB
Solved: 2026-11-15T01:54:28.478229+00:00
"""

# Time:  O(n)
# Space: O(1)

class Solution(object):
    def numOfSubarrays(self, arr):
        """
        :type arr: List[int]
        :rtype: int
        """
        MOD = 10**9+7
        result, accu = 0, 0
        dp = [1, 0]
        for x in arr:
            accu ^= x&1
            dp[accu] += 1
            result = (result + dp[accu^1]) % MOD
        return result
