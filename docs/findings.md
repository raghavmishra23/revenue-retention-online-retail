# Findings

Two years of trading, 1,027,015 cleaned invoice lines, 2009-12-01 to 2011-12-09. Every figure here
comes from the marts in `sql/02_marts` and can be reproduced with
`.venv/Scripts/python -m src.pipeline all`. All values are INR read at the source magnitudes; see
the provenance note in the README.

## The headline return rate is wrong by half, and I can name the invoices

The warehouse reports a return rate of **3.6433%**: ₹732,084.15 of cancellations against
₹20,094,028.49 of gross. Taken at face value that is a goods-quality problem worth most of a
million rupees.

It is not. **1,762 cancellation lines, worth −₹399,268.39, reverse an identical order placed the
same day by the same customer for the same SKU.** Same customer key, same product key, same
calendar day, exactly opposite quantity. Those are order-entry corrections — a line keyed wrong and
immediately backed out — not goods coming back. They are 9.7% of the 18,154 cancellation lines and
**54.54% of all returned value**.

The arithmetic:

```text
gross revenue                              20,094,028.49
returns, all cancellations                   -732,084.15   ->  3.6433%
same-day identical reversals                  399,268.39
returns excluding reversals                  -332,815.76   ->  1.6563%
```

**The genuine return rate is about 1.66%, not 3.64%.** The reported figure is more than double the
real one.

Two invoices carry most of it.

**Stock code 23843, "PAPER CRAFT , LITTLE BIRDIE".** Invoice `581483` books 80,995 units for
₹168,469.60 at 2011-12-09 09:15 for customer 16446. Invoice `C581484` reverses exactly −80,995
units for −₹168,469.60 at 09:27 the same morning, same customer. Twelve minutes apart, netting to
zero. That SKU has no other activity anywhere in the two years. A single mis-keyed line is 23.0% of
every rupee of returns in the dataset.

**Stock code 23166, "MEDIUM CERAMIC TOP STORAGE JAR".** Invoice `541431` books 74,215 units for
₹77,183.60 at 2011-01-18 10:01 for customer 12346. Invoice `C541433` reverses −74,215 units for
−₹77,183.60 at 10:17, sixteen minutes later. Unlike 23843, this SKU trades normally through the
rest of the year in quantities of 1 to 96.

Those two lines alone are **₹245,653.20, or 33.6% of all returned value**, and both are keystroke
corrections.

The distortion shows up in the monthly trend as two spikes that have nothing to do with trading.
January 2011 reports a 13.30% return rate and December 2011 reports 27.32%; those are the months
holding 23166 and 23843 respectively. Every other month in the series sits between 1.26% and 6.35%.

The concentration is extreme at the SKU grain too: **the twelve codes with the largest returned
value account for −₹327,272.88, 44.7% of all returns**, and the list is led by the two reversal
SKUs. Below them the pattern changes character: `22423` (Regency Cakestand) returns ₹16,545.30
across 341 separate lines at a 5.00% rate, `POST` returns ₹15,252.01 across 228 lines, and `23113`
returns 81.84% of its own gross across just 6 lines.

**Recommendations.**

1. **Report 1.66%, not 3.64%, and reconcile the gap in the footnote.** Any target set against the
   3.64% figure is chasing ₹399,268.39 of corrections that no process change can recover. The
   same-day reversal test is already in SQL; make it part of the standing definition.
2. **Put a confirmation step on single lines above 10,000 units.** Two lines — 80,995 and 74,215
   units — produced ₹245,653.20 of phantom returns, 33.6% of the total. The threshold costs
   nothing: no legitimate line in two years of data comes close to those quantities.
3. **Investigate the 341 return lines on SKU 22423 and the 6 on SKU 23113 as the actual quality
   signal.** After the reversals are stripped, ₹332,815.76 of genuine returns remain, and the
   repeat-return SKUs with high line counts are where the recoverable money is. SKU 23113 returning
   81.84% of its own gross on 6 lines is either a listing error or a defect, and it is a single
   afternoon's work to find out which.

## Where the revenue comes from, and how it trends

Net revenue is **₹19,361,944.34**: gross of ₹20,094,028.49 less ₹732,084.15 of returns, across
**39,675 orders** at an average order value of **₹506.47**. The trailing twelve months to November
2011 are **up 2.97%** on the twelve before, ₹9,587,708.87 against ₹9,311,012.09.

The business is sharply seasonal. Net revenue runs between ₹490,000 and ₹790,000 from January to
August, then climbs through September, October and November in both years. November 2011 is the
largest month in the series at **₹1,474,148.27 across 2,759 orders and 1,661 active customers** —
more than twice a typical spring month. The autumn ramp is visible in both years and is the single
strongest pattern in the trend.

Geographically the picture is concentrated and lopsided:

| Market | Net revenue | Orders | Customers | AOV | Return rate |
|---|---:|---:|---:|---:|---:|
| India | 16,480,801.54 | 36,242 | 5,357 | 472.52 | 3.76% |
| Ireland | 612,881.61 | 585 | 3 | 1,082.51 | 3.22% |
| Netherlands | 549,917.43 | 223 | 22 | 2,483.59 | 0.71% |
| Germany | 412,495.51 | 777 | 107 | 542.88 | 2.21% |
| France | 317,722.20 | 614 | 94 | 547.05 | 5.41% |
| Australia | 166,369.42 | 90 | 15 | 1,868.33 | 1.06% |
| Spain | 93,318.56 | 149 | 38 | 716.07 | 12.54% |

India is **85.12% of net revenue** on 36,242 of 39,675 orders. By region: India ₹16,480,801.54
across 5,357 customers, Europe ₹2,589,752.08 across 465, Asia-Pacific ₹237,125.21 across 29,
Middle East & Africa ₹28,990.20 across 15, Americas ₹14,370.15 across 17, and Unspecified
₹10,905.16 across 6.

The export markets behave nothing like the home market. India's AOV is ₹472.52; the Netherlands
sells 223 orders at **₹2,483.59 each**, more than five times as much, with the lowest return rate
of any market of its size at 0.71%. Ireland does ₹612,881.61 across **three customers** — that is
wholesale, not retail, and it is a concentration risk worth naming: losing one of those three
accounts would cost roughly 3% of total net revenue.

Among markets with 100 or more orders, **Spain is the clear return-rate outlier at 12.54%** on 149
orders, against a 3.76% home-market rate. France is second at 5.41% on 614 orders. Neither is
explained by the same-day reversals, both of which sit in the home market.

**Recommendations.**

1. **Audit Spain's 149 orders.** At 12.54% against a 3.76% baseline, Spain is losing ₹13,375.19 of
   its ₹106,693.75 gross to returns. Bringing it to the France rate would recover roughly ₹7,600;
   bringing it to the Netherlands rate would recover ₹12,600. The population is small enough to
   review order by order in an afternoon.
2. **Protect the Ireland and Netherlands accounts explicitly.** 25 customers across those two
   markets carry ₹1,162,799.04, 6.0% of net revenue, at average order values of ₹1,082 and ₹2,483.
   They are not covered by any retention campaign aimed at the 5,357 home-market customers.
3. **Staff and stock to the autumn ramp.** September to November 2011 delivered ₹3,595,061.52,
   18.6% of all net revenue in the series, in three of 25 months. The same shape appears in 2010.

## Which customers to retain

**5,854 customers are scoreable** — identified, with at least one non-cancelled sales line. They
account for **₹16,493,962.86** of attributable net revenue. Average customer value is **₹2,817.55**
and **72.46% have ordered more than once**, which is a high repeat rate and the strongest thing in
the customer picture.

| Segment | Customers | % of customers | Net revenue | % of revenue | Avg value | Avg orders | Avg days since order |
|---|---:|---:|---:|---:|---:|---:|---:|
| Champions | 1,464 | 25.01% | 11,570,733.29 | 70.15% | 7,903.51 | 15.7 | 19.5 |
| Loyal | 1,220 | 20.84% | 2,444,972.89 | 14.82% | 2,004.08 | 5.4 | 77.3 |
| Cannot Lose Them | 230 | 3.93% | 892,183.84 | 5.41% | 3,879.06 | 9.1 | 341.1 |
| At Risk | 598 | 10.22% | 550,074.31 | 3.34% | 919.86 | 3.4 | 377.6 |
| Potential Loyalist | 829 | 14.16% | 424,492.73 | 2.57% | 512.05 | 1.4 | 63.4 |
| Lost | 896 | 15.31% | 353,656.53 | 2.14% | 394.71 | 1.2 | 554.0 |
| Hibernating | 617 | 10.54% | 257,849.26 | 1.56% | 417.91 | 1.3 | 314.0 |

### Champions are a dependency, not only a success

**1,464 customers — 25.01% of the book — carry 70.15% of attributable revenue**, which is 59.76% of
all net revenue including guest sales. They average 15.7 orders and ₹7,903.51 each, and they
ordered 19.5 days ago on average, so they are currently healthy.

That is also the exposure. A 10% loss of Champion revenue is **₹1,157,073.33**, six times what the
entire Hibernating segment is worth and more than the At Risk and Lost segments combined. There is
no second tier that could absorb it: Loyal, the next segment down, is 20.84% of customers and
14.82% of revenue, with an average value a quarter of a Champion's. The retention plan has to treat
Champion attrition as the primary revenue risk in the business, not as a nice-to-have.

### 828 customers are visibly slipping

**At Risk and Cannot Lose Them together are 828 customers holding ₹1,442,258.15.** They are defined
by lapse, not by weakness: Cannot Lose Them average 9.1 orders and ₹3,879.06 each and have been
silent for **341 days**; At Risk average 3.4 orders and ₹919.86 and have been silent for **378
days**. These are people who bought repeatedly and then stopped.

That is the sharpest target in the dataset. The 230 in Cannot Lose Them alone hold ₹892,183.84 at
₹3,879 each, which is more than half the Champions' average value — recovering even a fifth of that
segment is worth ₹178,000.

### Retention is flat after the first month, which is the good news

Across 25 monthly cohorts, retention at offset 0 is exactly 100% by construction, then:

| Offset | M1 | M2 | M3 | M4 | M5 | M6 | M7 | M12 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Average retention | 21.14% | 22.00% | 21.72% | 20.58% | 18.84% | 17.88% | 17.76% | 18.30% |

The interesting part is not the drop, it is what happens after it. The curve falls to 21.14% in
month 1 and then **does not keep falling**: month 2 is slightly higher than month 1, months 3 and 4
hold above 20%, and by month 12 it is 18.30% — only 2.8 points below month 1 after a full year.
Most retail cohort curves decay steadily toward zero. This one drops once and then flattens.

The reading is that there are two distinct populations inside every cohort. Roughly four in five
customers are one-time buyers who never come back, and they are gone by month 1. The one in five
who make a second purchase are habitual and keep buying for years. The December 2009 cohort makes
this concrete: 953 customers, 34.94% active in month 1, **37.57% still active in month 12**, and
19.73% still active in month 24 — two years later.

That changes what retention spend is for. Month-2 reactivation campaigns aimed at the whole cohort
are working against a population that has largely already decided. The gain is in the first
purchase-to-second-purchase conversion, and in keeping the 20% who convert, because they stay for
years.

**Recommendations.**

1. **Run a win-back on the 828 At Risk and Cannot Lose Them customers, prioritising the 230 in
   Cannot Lose Them.** They hold ₹1,442,258.15, they averaged 9.1 and 3.4 orders respectively, and
   they have been silent for 341 and 378 days. At a 20% recovery rate on the Cannot Lose Them
   segment alone the return is ₹178,436.
2. **Instrument Champion attrition as a monitored metric with a defined threshold.** 1,464
   customers hold ₹11,570,733.29. A 10% loss is ₹1,157,073.33, and at an average recency of 19.5
   days a Champion going quiet for 60 days is already a detectable signal.
3. **Move first-to-second-purchase conversion to the top of the retention budget.** 1,725
   customers sit in Potential Loyalist and Lost with an average of 1.4 and 1.2 orders — they bought
   once and stopped. Cohort month 1 retention of 21.14% is where the whole curve is set, and it
   does not decay much afterwards, so a point gained there is a point held for a year.
4. **Treat the guest population as a measurement gap to close, not a segment to ignore.** 229,202
   rows worth ₹2,724,218.55 — 22.3% of rows and 14.3% of revenue — have no customer ID and cannot
   be scored, retained or attributed. Capturing identity at checkout is the single change that
   would most improve every number in this section.

## Which products carry the revenue

The catalogue is 4,746 trading SKUs after shipping, adjustment and test codes are excluded.

**1,038 SKUs — 21.87% of the catalogue — carry 80% of net revenue**, ₹15,143,586.01. The remaining
**3,708 SKUs carry ₹3,784,947.82**, averaging ₹1,020.75 each across two years. That is close to the
textbook 80/20 shape and slightly sharper than it.

The top of the curve is dominated by homewares and bags: `22423` Regency Cakestand 3 Tier at
₹314,045.02 on 25,028 units, `85123A` White Hanging Heart T-Light Holder at ₹251,781.63 on 91,082
units, `85099B` Jumbo Bag Red Retrospot at ₹180,512.16 on 95,963 units, `47566` Party Bunting at
₹147,079.73, and `84879` Assorted Colour Bird Ornament at ₹128,550.42.

At the other end, **23 SKUs net negative, totalling −₹564.26**. That is a trivial sum and it is the
honest reason the Pareto curve is allowed to dip: the build gate permits a fall in cumulative share
only where a SKU nets below zero.

I have no cost data, so none of this is margin. Everything above is revenue concentration, and a
high-revenue SKU could still be the least profitable thing in the catalogue.

**Recommendations.**

1. **Review the 3,708 tail SKUs for range rationalisation, not the 23 negative ones.** The negative
   SKUs are worth −₹564.26 in total and are noise. The tail is 78.13% of the catalogue carrying
   20% of revenue at ₹1,020.75 per SKU over two years, and that is where holding cost, listing
   effort and warehouse space are being spent.
2. **Put availability guarantees on the 1,038 band SKUs.** They carry ₹15,143,586.01. A stockout in
   that band during the September-to-November ramp, which is 18.6% of annual revenue in three
   months, is the most expensive operational failure available.
3. **Get cost data before any assortment decision is made final.** Every ranking in this section is
   revenue. The five SKUs above move between 25,000 and 96,000 units at low unit prices, and
   without cost they cannot be separated from the cakestand that makes ₹314,045.02 on a quarter of
   the volume.

## Caveats

- **December 2011 is a partial month.** The extract ends on 9 December, so 2011-12 holds nine
  trading days. Its **−68.58% month-on-month fall is the calendar, not a trading collapse**, and
  its 27.32% return rate is the SKU 23843 reversal. It is excluded from the year-on-year window,
  which compares the twelve months to November 2011 against the twelve before.
- **Guests are unattributable.** 229,202 rows worth ₹2,724,218.55 count toward revenue and are
  absent from every customer figure, so segment revenue shares are of ₹16,493,962.86, not of
  ₹19,361,944.34.
- **85 identified customers are unscoreable.** 62 appear only on adjustment or test lines and 23
  only on cancellations, so 5,854 of 5,939 are segmented.
- **Revenue, not margin.** There is no cost or discount data in the source.
- **The home market is relabelled.** Values are read as INR at the source magnitudes with no rate
  conversion; the magnitudes are the original retailer's.
