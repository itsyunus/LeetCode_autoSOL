"""
1606. Find Servers That Handled Most Number of Requests
Difficulty: Hard
Runtime: 154 ms
Memory: 125.5 MB
Solved: 2026-11-09T06:00:52.843561+00:00
"""

#include <vector>
#include <queue>
#include <set>
#include <algorithm>

using namespace std;

class Solution {
public:
    vector<int> busiestServers(int k, vector<int>& arrival, vector<int>& load) {
        vector<int> requestCount(k, 0);
        // Min-heap to track busy servers: pair of (finish_time, server_id)
        priority_queue<pair<long long, int>, vector<pair<long long, int>>, greater<pair<long long, int>>> busy;
        
        // Set of currently available server IDs
        set<int> available;
        for (int i = 0; i < k; ++i) {
            available.insert(i);
        }

        int n = arrival.size();
        for (int i = 0; i < n; ++i) {
            long long curTime = arrival[i];
            long long duration = load[i];

            // Free servers that have completed their requests by curTime
            while (!busy.empty() && busy.top().first <= curTime) {
                available.insert(busy.top().second);
                busy.pop();
            }

            // If no servers are available, the request is dropped
            if (available.empty()) {
                continue;
            }

            int target = i % k;
            auto it = available.lower_bound(target);
            if (it == available.end()) {
                it = available.begin();
            }

            int serverId = *it;
            available.erase(it);
            busy.push({curTime + duration, serverId});
            requestCount[serverId]++;
        }

        int maxRequests = *max_element(requestCount.begin(), requestCount.end());
        vector<int> result;
        for (int i = 0; i < k; ++i) {
            if (requestCount[i] == maxRequests) {
                result.push_back(i);
            }
        }

        return result;
    }
};