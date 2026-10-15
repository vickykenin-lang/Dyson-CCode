"""Dyson Sphere Layer A Entry Gateway (Step 8).

Every Founder session is authenticated here and every request is rate limited. Authenticated
requests go to the Conversation Engine (B) and nowhere else. The Gateway has no approval, STOP or
PAUSE endpoint: those live only on Direct Founder Controls (LA-DFC-01).
"""
