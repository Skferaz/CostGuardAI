"""
CostGuard AI — Architecture Diagram Generator
Run: python docs/generate_diagram.py
Output: docs/architecture.png
"""
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch

fig, ax = plt.subplots(figsize=(24, 14))
fig.patch.set_facecolor('#0f172a')
ax.set_facecolor('#0f172a')
ax.set_xlim(0, 24)
ax.set_ylim(0, 14)
ax.axis('off')

# ─── Helpers ──────────────────────────────────────────────────────────────────

def draw_box(x, y, w, h, title, sub='', bg='#1e293b', border='#475569',
             title_color='#e2e8f0', sub_color='#94a3b8', badge=None, badge_color='#38bdf8'):
    rect = FancyBboxPatch((x, y), w, h,
        boxstyle="round,pad=0.04,rounding_size=0.2",
        linewidth=1.8, edgecolor=border, facecolor=bg, zorder=3)
    ax.add_patch(rect)
    cy = y + h / 2
    offset = 0.15 if sub else 0
    ax.text(x + w/2, cy + offset, title,
        ha='center', va='center', fontsize=8.5, fontweight='bold',
        color=title_color, zorder=4, wrap=True)
    if sub:
        ax.text(x + w/2, cy - 0.22, sub,
            ha='center', va='center', fontsize=7, color=sub_color, zorder=4)
    if badge:
        bw = 0.6
        brect = FancyBboxPatch((x + w - bw - 0.06, y + h - 0.32), bw, 0.25,
            boxstyle="round,pad=0.02", linewidth=0, facecolor=badge_color, zorder=5)
        ax.add_patch(brect)
        ax.text(x + w - bw/2 - 0.06, y + h - 0.19, badge,
            ha='center', va='center', fontsize=6, color='#0f172a',
            fontweight='bold', zorder=6)

def draw_cluster(x, y, w, h, label, bg='#1e293b', border='#334155', alpha=0.35):
    rect = FancyBboxPatch((x, y), w, h,
        boxstyle="round,pad=0.06,rounding_size=0.35",
        linewidth=2, edgecolor=border, facecolor=bg, alpha=alpha, zorder=1)
    ax.add_patch(rect)
    ax.text(x + 0.18, y + h - 0.02, label,
        ha='left', va='top', fontsize=8, fontweight='bold',
        color=border, zorder=2)

def arr(x1, y1, x2, y2, color='#38bdf8', lw=1.4, label='', rad=0.0):
    ax.annotate('', xy=(x2, y2), xytext=(x1, y1),
        arrowprops=dict(arrowstyle='->', color=color, lw=lw,
                        connectionstyle=f'arc3,rad={rad}'), zorder=6)
    if label:
        mx = (x1+x2)/2 + (0.05 if rad == 0 else rad * 0.5)
        my = (y1+y2)/2
        ax.text(mx, my, label, fontsize=6.5, color=color, ha='center', va='center',
            zorder=7, bbox=dict(boxstyle='round,pad=0.15', fc='#0f172a', ec='none', alpha=0.9))

# ═══════════════════════════════════════════════════════════════════════════════
#  LAYOUT
# ═══════════════════════════════════════════════════════════════════════════════

# ── Title ──────────────────────────────────────────────────────────────────────
ax.text(12, 13.65, 'CostGuard AI  -  AWS Architecture',
    ha='center', va='top', fontsize=22, fontweight='bold',
    color='#e2e8f0', zorder=10)
ax.text(12, 13.1, 'Serverless SaaS  |  Multi-tenant  |  AI-Powered Cost Intelligence',
    ha='center', va='top', fontsize=11, color='#64748b', zorder=10)

# ── USER (far left) ────────────────────────────────────────────────────────────
draw_box(0.2, 9.2, 2.2, 1.2, 'USER', 'Browser / Mobile', '#1e293b', '#475569')

# ── EDGE & AUTH ────────────────────────────────────────────────────────────────
draw_cluster(0.1, 6.0, 2.4, 3.0, 'Edge & Auth', '#0c2340', '#38bdf8')
draw_box(0.3, 7.9, 2.0, 0.9, 'CloudFront', 'CDN  |  HTTPS  |  OAC', '#0c2340', '#38bdf8', '#e2e8f0')
draw_box(0.3, 6.8, 2.0, 0.9, 'S3 Bucket', 'index.html (Private)', '#0c2340', '#38bdf8', '#e2e8f0')
draw_box(0.3, 6.1, 2.0, 0.6, 'Cognito', 'JWT Tokens', '#1a1040', '#818cf8', '#e2e8f0')

# ── API LAYER ──────────────────────────────────────────────────────────────────
draw_cluster(3.1, 6.0, 3.0, 3.0, 'API Layer', '#0c2340', '#38bdf8')
draw_box(3.3, 8.3, 2.6, 0.55, 'API Gateway', '17 REST Routes', '#0c2340', '#38bdf8', '#e2e8f0')
draw_box(3.3, 6.1, 2.6, 2.0, 'Dashboard API Lambda', 'Python 3.11  |  512 MB  |  30s\n\nchat  /  recommendations\nbudgets  /  service-detail\npayments  /  onboard  /  auth',
    '#0c2340', '#60a5fa', '#e2e8f0', '#94a3b8')

# ── DYNAMODB ───────────────────────────────────────────────────────────────────
draw_cluster(6.8, 5.5, 3.0, 4.0, 'DynamoDB  (4 Tables  |  PAY_PER_REQUEST)', '#052e16', '#34d399')
draw_box(7.0, 8.7, 2.6, 0.7, 'costguard-customers', 'PK: customerId', '#052e16', '#34d399', '#e2e8f0')
draw_box(7.0, 7.8, 2.6, 0.7, 'costguard-costs', 'PK: customerId   SK: date', '#052e16', '#34d399', '#e2e8f0')
draw_box(7.0, 6.9, 2.6, 0.7, 'costguard-alerts', 'PK: alertId  (idempotent)', '#4c0519', '#fb7185', '#e2e8f0')
draw_box(7.0, 5.6, 2.6, 1.1, 'costguard-budgets', 'PK: customerId   SK: service\nSSE  |  PITR  |  DeletionPolicy:Retain',
    '#052e16', '#34d399', '#e2e8f0', '#6ee7b7')

# ── BEDROCK ────────────────────────────────────────────────────────────────────
draw_cluster(10.5, 5.5, 3.2, 4.0, 'Amazon Bedrock  (Claude AI Models)', '#1a0a2e', '#c084fc')
draw_box(10.7, 8.7, 2.8, 0.8, 'Claude Haiku 4.5', 'us.anthropic.claude-haiku-4-5-20251001-v1:0', '#1a0a2e', '#818cf8', '#e2e8f0', '#94a3b8', 'FREE', '#64748b')
draw_box(10.7, 7.7, 2.8, 0.8, 'Claude Sonnet 4.5', 'us.anthropic.claude-sonnet-4-5-20250929-v1:0', '#1a0a2e', '#a78bfa', '#e2e8f0', '#94a3b8', 'PRO', '#2563eb')
draw_box(10.7, 6.7, 2.8, 0.8, 'Claude Opus 4.6', 'us.anthropic.claude-opus-4-6-v1', '#2d1b69', '#c084fc', '#e2e8f0', '#94a3b8', 'ENT', '#7c3aed')
ax.text(12.1, 6.35, 'Model selected server-side by DynamoDB plan field\nCross-Region Inference Profiles (us. prefix)',
    ha='center', va='center', fontsize=6.5, color='#64748b', style='italic', zorder=4)

# ── PAYMENTS ───────────────────────────────────────────────────────────────────
draw_cluster(10.5, 4.1, 3.2, 1.2, 'Payments', '#2e0a1a', '#fb7185')
draw_box(10.7, 4.3, 2.8, 0.8, 'Razorpay Standard Checkout', 'Rs.999/month  |  HMAC-SHA256 Verified\nKEY_SECRET never reaches browser', '#2e0a1a', '#fb7185', '#e2e8f0', '#fca5a5')

# ── CUSTOMER ACCOUNT ───────────────────────────────────────────────────────────
draw_cluster(14.5, 5.5, 4.0, 4.0, 'Customer AWS Account  (Cross-Account via STS AssumeRole)', '#0a2e1a', '#34d399')
draw_box(14.7, 8.7, 3.6, 0.7, 'CostGuardReadRole', 'Read-Only IAM  |  Trust: costguard-lambda-role only', '#052e16', '#34d399', '#e2e8f0')
draw_box(14.7, 7.8, 3.6, 0.7, 'Cost Explorer API', 'GetCostAndUsage  |  GetCostForecast', '#052e16', '#34d399', '#e2e8f0')
draw_box(14.7, 6.9, 3.6, 0.7, 'Resource Inventory', 'EC2  |  S3  |  Lambda  |  RDS  |  CloudFront', '#052e16', '#86efac', '#0f172a')
draw_box(14.7, 5.6, 3.6, 1.1, 'Temp Credentials', 'TTL: 1 hour  |  Never stored\nSTS AssumeRole per request', '#052e16', '#34d399', '#e2e8f0', '#6ee7b7')

# ── IaC ────────────────────────────────────────────────────────────────────────
draw_cluster(19.2, 6.0, 4.6, 3.5, 'Infrastructure as Code', '#2e2a0a', '#fbbf24')
draw_box(19.4, 8.7, 4.2, 0.7, 'CloudFormation', 'Single template  |  30+ Resources  |  1 deploy command', '#2e2a0a', '#fbbf24', '#e2e8f0')
draw_box(19.4, 7.8, 4.2, 0.7, 'Public S3 Bucket', 'CF Template for one-click customer onboarding', '#2e2a0a', '#fbbf24', '#e2e8f0')
draw_box(19.4, 6.9, 4.2, 0.7, 'GitHub', 'Skferaz/CostGuardAI  |  Public repo', '#1e293b', '#475569', '#e2e8f0')
draw_box(19.4, 6.1, 4.2, 0.6, '.env.example', 'Credentials template  |  .env in .gitignore', '#4c0519', '#fb7185', '#e2e8f0')

# ── DAILY SCHEDULER (bottom row) ───────────────────────────────────────────────
draw_cluster(0.1, 0.5, 14.0, 4.8, 'Daily Cost Analyzer  -  Runs at 6 AM UTC  (EventBridge Cron Schedule)', '#2e1a0a', '#fb923c')
draw_box(0.3, 1.8, 2.0, 1.0, 'EventBridge', 'cron(0 6 * * ? *)', '#2e1a0a', '#fb923c', '#e2e8f0')
draw_box(3.0, 1.8, 2.5, 1.0, 'Cost Analyzer Lambda', 'Python 3.11  |  512MB  |  5min', '#2e1a0a', '#fb923c', '#e2e8f0')
draw_box(6.3, 1.8, 2.0, 1.0, 'STS AssumeRole', 'Per customer\n(loop)', '#0a2e1a', '#34d399', '#e2e8f0')
draw_box(9.1, 1.8, 2.2, 1.0, 'Cost Explorer', 'Yesterday + 7-day\nhistory', '#052e16', '#34d399', '#e2e8f0')
draw_box(0.3, 0.7, 2.5, 0.9, 'DynamoDB Write', 'costs table + alerts table', '#052e16', '#34d399', '#e2e8f0')
draw_box(3.5, 0.7, 2.5, 0.9, 'SES Email Alert', 'On spike > 20% vs 7-day avg', '#4c0519', '#fb7185', '#e2e8f0')
draw_box(6.5, 0.7, 2.5, 0.9, 'Bedrock Claude', 'AI cost analysis\n+ recommendations', '#1a0a2e', '#c084fc', '#e2e8f0')
draw_box(9.5, 0.7, 4.3, 0.9, 'Spike Detection Logic: if (today - avg7) / avg7 > 0.20: alert()',
    '#2e1a0a', '#fb923c', '#fb923c', '#fb923c')

# ═══════════════════════════════════════════════════════════════════════════════
#  ARROWS
# ═══════════════════════════════════════════════════════════════════════════════
CYAN   = '#38bdf8'
GREEN  = '#34d399'
PURPLE = '#c084fc'
ORANGE = '#fb923c'
RED    = '#fb7185'
YELLOW = '#fbbf24'
INDIGO = '#818cf8'

# User → CloudFront
arr(1.3, 9.2, 1.3, 8.8, CYAN, label='HTTPS')
# User → Cognito
arr(1.0, 9.2, 0.9, 6.7, INDIGO, lw=1.2, label='Auth', rad=0.3)
# User → API Gateway
arr(2.3, 9.6, 3.3, 8.58, INDIGO, label='Bearer JWT', rad=-0.1)

# CF → API
arr(2.3, 8.35, 3.3, 8.45, CYAN, label='')

# API GW → Lambda
arr(4.6, 8.3, 4.6, 8.1, CYAN)

# Lambda → DynamoDB (4 arrows)
arr(6.3, 7.8, 7.0, 9.05, GREEN, lw=1.2)
arr(6.3, 7.5, 7.0, 8.15, GREEN, lw=1.2)
arr(6.3, 7.2, 7.0, 7.25, RED, lw=1.2)
arr(6.3, 6.9, 7.0, 6.1, GREEN, lw=1.2)

# Lambda → Bedrock (3 model arrows)
arr(6.3, 8.0, 10.7, 9.1, '#64748b', lw=1.0, label='Free')
arr(6.3, 7.5, 10.7, 8.1, '#2563eb', lw=1.2, label='Pro')
arr(6.3, 7.0, 10.7, 7.1, '#7c3aed', lw=1.2, label='Enterprise')

# Lambda → Customer Account (STS)
arr(6.3, 7.6, 14.7, 9.05, GREEN, lw=1.5, label='STS AssumeRole', rad=-0.15)
# Customer Account internal
arr(16.5, 8.7, 16.5, 8.5, GREEN, lw=1.2)
arr(16.5, 7.8, 16.5, 7.6, GREEN, lw=1.2)

# Lambda → Razorpay
arr(6.0, 7.1, 10.7, 4.75, RED, lw=1.3, label='HMAC verify', rad=0.2)

# Daily Analyzer
arr(2.3, 2.3, 3.0, 2.3, ORANGE)
arr(5.5, 2.3, 6.3, 2.3, GREEN)
arr(8.3, 2.3, 9.1, 2.3, GREEN)
arr(3.0, 1.8, 0.8, 1.6, GREEN, lw=1.2, label='write', rad=0.15)
arr(3.5, 1.8, 4.25, 1.6, RED, lw=1.2, label='alert')
arr(6.3, 1.8, 7.25, 1.6, PURPLE, lw=1.2, label='AI')
# Scheduler → Customer
arr(7.3, 2.3, 14.7, 9.35, GREEN, lw=1.3, label='STS (per customer)', rad=-0.2)

# CloudFormation → Lambda (dashed)
ax.annotate('', xy=(5.5, 8.6), xytext=(19.4, 8.35),
    arrowprops=dict(arrowstyle='->', color=YELLOW, lw=1.3, linestyle='dashed',
                    connectionstyle='arc3,rad=0.25'), zorder=6)
ax.text(13.5, 9.15, 'provisions', fontsize=7, color=YELLOW, style='italic',
    ha='center', zorder=7)

# ── Legend ─────────────────────────────────────────────────────────────────────
items = [
    (CYAN,   'User / API Traffic'),
    (GREEN,  'Cross-Account Access'),
    (PURPLE, 'AI / Bedrock'),
    (RED,    'Payments / Alerts'),
    (ORANGE, 'Daily Scheduler'),
    (YELLOW, 'Infrastructure'),
]
ax.text(0.2, 0.42, 'LEGEND:', fontsize=7.5, fontweight='bold', color='#64748b', zorder=10)
for i, (c, lbl) in enumerate(items):
    bx = 1.4 + i * 3.7
    ax.plot([bx, bx + 0.5], [0.38, 0.38], color=c, lw=2.5, zorder=10)
    ax.text(bx + 0.6, 0.38, lbl, fontsize=7, color=c, va='center', zorder=10)

# Footer
ax.text(12, 0.08,
    'github.com/Skferaz/CostGuardAI   |   Live: https://d3e1nh6uj1h44y.cloudfront.net',
    ha='center', va='bottom', fontsize=8, color='#334155', zorder=10)

plt.tight_layout(pad=0.2)
out = os.path.join(os.path.dirname(__file__), 'architecture.png')
plt.savefig(out, dpi=160, bbox_inches='tight',
            facecolor='#0f172a', edgecolor='none')
plt.close()
print(f'Saved: {out}')
