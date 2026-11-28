"""
3947. Maximum Number of Items From Sale II
Difficulty: Medium
Runtime: 148 ms
Memory: 304.7 MB
Solved: 2026-11-28T08:27:00.843122+00:00
"""

#include <vector>
#include <algorithm>

using namespace std;

class Solution {
public:
    int maximumSaleItems(vector<vector<int>>& items, int budget) {
        int n = items.size();
        
        // Count frequencies of each factor
        vector<int> count(n + 1, 0);
        for (const auto& item : items) {
            count[item[0]]++;
        }
        
        // multiple_count[v] = number of items whose factor is a multiple of v
        vector<int> multiple_count(n + 1, 0);
        for (int i = 1; i <= n; ++i) {
            for (int j = i; j <= n; j += i) {
                multiple_count[i] += count[j];
            }
        }
        
        long long min_price = items[0][1];
        for (const auto& item : items) {
            min_price = min(min_price, (long long)item[1]);
        }
        
        // Collect candidate value-2 items
        // Each copy of these items yields 2 items for price_i
        struct Candidate {
            long long price;
            int gain;
        };
        
        vector<Candidate> candidates;
        for (const auto& item : items) {
            int factor = item[0];
            long long price = item[1];
            int gain = multiple_count[factor] - 1;
            
            if (gain > 0 && price < 2 * min_price) {
                candidates.push_back({price, gain});
            }
        }
        
        // Sort candidates by price ascending
        sort(candidates.begin(), candidates.end(), [](const Candidate& a, const Candidate& b) {
            return a.price < b.price;
        });
        
        long long total_items = 0;
        long long rem_budget = budget;
        
        for (const auto& cand : candidates) {
            if (rem_budget == 0) break;
            long long take = min((long long)cand.gain, rem_budget / cand.price);
            total_items += take * 2;
            rem_budget -= take * cand.price;
        }
        
        // Remaining budget buys copies of the cheapest item (1 item each)
        total_items += rem_budget / min_price;
        
        return total_items;
    }
};