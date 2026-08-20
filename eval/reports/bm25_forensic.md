# BM25 forensic analysis (M3-B, no tuning)

corpus revision 2; focus queries: q13_ar_workplace, q10_vaccine_logistics, q12_ocean_plastic, q02_quantum_computing, q01_ev_battery_recycling

Method: naive = 3:1 title/description term-count (baseline.py). BM25 core = production ranker (k1=1.5, b=0.75, smoothed IDF, 2:1 field weighting, self-match normalization, no bonuses). Every variant below is measured as a separate experiment; none changes the production ranker.

## q13_ar_workplace — 'augmented reality workplace training'

items=23 relevance 0/1/2 = 7/9/7

query-term IDF (title field / description field):
  augmented              2.2618   2.7726
  reality                1.4733   2.7726
  workplace              2.7726   1.9253
  training               0.8267   1.1632

top-10 naive:
   # id                     rel   score  title
   1 q13_03                   2  8.0000  Augmented reality
   2 q13_21                   0  7.0000  Augmented reality gaming platform launches ...
   3 q13_22                   1  7.0000  Workplace training budgets rise this year
   4 q13_14                   1  5.0000  Employee training
   5 q13_04                   1  4.0000  Does AR training actually improve retention?
   6 q13_02                   2  4.0000  Factories cut onboarding time using AR trai...
   7 q13_13                   1  4.0000  r/technology: AR training demos worth trying
   8 q13_01                   2  3.0000  AR training slashes onboarding time at fact...
   9 q13_08                   2  3.0000  AR training slashes onboarding time at fact...
  10 q13_15                   2  3.0000  AR training slashes onboarding time at fact...

top-10 BM25 core:
   # id                     rel   score  title
   1 q13_03                   2  0.6625  Augmented reality
   2 q13_21                   0  0.3574  Augmented reality gaming platform launches ...
   3 q13_22                   1  0.3123  Workplace training budgets rise this year
   4 q13_14                   1  0.2298  Employee training
   5 q13_09                   1  0.1635  Virtual reality
   6 q13_20                   1  0.1109  Manufacturers adopt mixed reality for quali...
   7 q13_23                   0  0.1109  Reality TV show returns for new season
   8 q13_06                   0  0.1099  AR glasses for consumers hit the market
   9 q13_13                   1  0.1037  r/technology: AR training demos worth trying
  10 q13_04                   1  0.1036  Does AR training actually improve retention?

rank of relevant items (rel>=1): naive # -> BM25 core #
  q13_03                 rel=2  naive# 1  bm25#1
  q13_22                 rel=1  naive# 3  bm25#3
  q13_14                 rel=1  naive# 4  bm25#4
  q13_04                 rel=1  naive# 5  bm25#10
  q13_02                 rel=2  naive# 6  bm25#11
  q13_13                 rel=1  naive# 7  bm25#9
  q13_01                 rel=2  naive# 8  bm25#13
  q13_08                 rel=2  naive# 9  bm25#15
  q13_15                 rel=2  naive#10  bm25#12
  q13_18                 rel=2  naive#11  bm25#14
  q13_10                 rel=2  naive#12  bm25#16
  q13_20                 rel=1  naive#13  bm25#6
  q13_09                 rel=1  naive#15  bm25#5
  q13_17                 rel=1  naive#18  bm25#20
  q13_11                 rel=1  naive#19  bm25#21
  q13_05                 rel=1  naive#23  bm25#23

harmful inversions (BM25 puts worse above better), top by rel gap: 0 total
relevant items in top-10: naive=9 bm25=7

## q10_vaccine_logistics — 'vaccine cold chain logistics'

items=23 relevance 0/1/2 = 8/8/7

query-term IDF (title field / description field):
  vaccine                0.9268   2.2618
  cold                   0.7357   1.6740
  chain                  0.7357   1.9253
  logistics              1.9253   1.3063

top-10 naive:
   # id                     rel   score  title
   1 q10_02                   2 11.0000  New cold chain tech aims to cut vaccine waste
   2 q10_21                   0 10.0000  Cold chain logistics firm expands delivery ...
   3 q10_01                   2  9.0000  Cold chain innovation could cut vaccine waste
   4 q10_08                   2  9.0000  Cold chain innovation could cut vaccine waste
   5 q10_14                   2  9.0000  Cold chain innovation could cut vaccine waste
   6 q10_17                   2  9.0000  Cold chain innovation could cut vaccine waste
   7 q10_10                   2  9.0000  Cold chain innovation could cut vaccine was...
   8 q10_05                   1  8.0000  r/publichealth: cold chain failures are sti...
   9 q10_13                   1  6.0000  r/science: new cold chain sensor paper rele...
  10 q10_03                   2  6.0000  Cold chain

top-10 BM25 core:
   # id                     rel   score  title
   1 q10_21                   0  0.4749  Cold chain logistics firm expands delivery ...
   2 q10_15                   1  0.4452  Logistics
   3 q10_02                   2  0.4236  New cold chain tech aims to cut vaccine waste
   4 q10_05                   1  0.3651  r/publichealth: cold chain failures are sti...
   5 q10_20                   0  0.2941  Weekly health digest: trials, logistics, an...
   6 q10_17                   2  0.2512  Cold chain innovation could cut vaccine waste
   7 q10_01                   2  0.2512  Cold chain innovation could cut vaccine waste
   8 q10_14                   2  0.2512  Cold chain innovation could cut vaccine waste
   9 q10_08                   2  0.2512  Cold chain innovation could cut vaccine waste
  10 q10_03                   2  0.2427  Cold chain

rank of relevant items (rel>=1): naive # -> BM25 core #
  q10_02                 rel=2  naive# 1  bm25#3
  q10_01                 rel=2  naive# 3  bm25#7
  q10_08                 rel=2  naive# 4  bm25#9
  q10_14                 rel=2  naive# 5  bm25#8
  q10_17                 rel=2  naive# 6  bm25#6
  q10_10                 rel=2  naive# 7  bm25#11
  q10_05                 rel=1  naive# 8  bm25#4
  q10_13                 rel=1  naive# 9  bm25#18
  q10_03                 rel=2  naive#10  bm25#10
  q10_19                 rel=1  naive#12  bm25#13
  q10_22                 rel=1  naive#13  bm25#15
  q10_15                 rel=1  naive#15  bm25#2
  q10_09                 rel=1  naive#17  bm25#16
  q10_11                 rel=1  naive#21  bm25#23
  q10_04                 rel=1  naive#22  bm25#22

harmful inversions (BM25 puts worse above better), top by rel gap: 5 total
  New cold chain tech aims to cut vaccine waste (rel 2) naive#1->bm25#3 [bm25 0.4236]
    pushed below Cold chain logistics firm expands delivery ... (rel 0) naive#2->bm25#1 [bm25 0.4749]
  Cold chain innovation could cut vaccine waste (rel 2) naive#6->bm25#6 [bm25 0.2512]
    pushed below r/publichealth: cold chain failures are sti... (rel 1) naive#8->bm25#4 [bm25 0.3651]
  Cold chain innovation could cut vaccine waste (rel 2) naive#5->bm25#8 [bm25 0.2512]
    pushed below r/publichealth: cold chain failures are sti... (rel 1) naive#8->bm25#4 [bm25 0.3651]
  Cold chain innovation could cut vaccine waste (rel 2) naive#3->bm25#7 [bm25 0.2512]
    pushed below r/publichealth: cold chain failures are sti... (rel 1) naive#8->bm25#4 [bm25 0.3651]
  Cold chain innovation could cut vaccine waste (rel 2) naive#4->bm25#9 [bm25 0.2512]
    pushed below r/publichealth: cold chain failures are sti... (rel 1) naive#8->bm25#4 [bm25 0.3651]
relevant items in top-10: naive=9 bm25=8

## q12_ocean_plastic — 'ocean plastic cleanup technology'

items=23 relevance 0/1/2 = 8/8/7

query-term IDF (title field / description field):
  ocean                  1.1632   2.7726
  plastic                0.5754   2.2618
  cleanup                1.0380   0.9268
  technology             2.2618   2.2618

top-10 naive:
   # id                     rel   score  title
   1 q12_01                   2 10.0000  Ocean plastic cleanup system passes key test
   2 q12_09                   2  9.0000  Ocean plastic cleanup system passes key test
   3 q12_16                   2  9.0000  Ocean plastic cleanup system passes key test
   4 q12_19                   2  9.0000  Ocean plastic cleanup system passes key test
   5 q12_11                   2  9.0000  Ocean plastic cleanup system passes key tes...
   6 q12_04                   1  7.0000  Can technology really clean up the ocean?
   7 q12_21                   0  7.0000  Ocean plastic waste statistics revised down...
   8 q12_02                   2  7.0000  Plastic cleanup array passes a key test at sea
   9 q12_22                   1  6.0000  Cleanup technology startup pivots to river ...
  10 q12_23                   0  5.0000  Plastic packaging tax comes into force

top-10 BM25 core:
   # id                     rel   score  title
   1 q12_04                   1  0.3846  Can technology really clean up the ocean?
   2 q12_22                   1  0.3259  Cleanup technology startup pivots to river ...
   3 q12_01                   2  0.2923  Ocean plastic cleanup system passes key test
   4 q12_16                   2  0.2546  Ocean plastic cleanup system passes key test
   5 q12_19                   2  0.2546  Ocean plastic cleanup system passes key test
   6 q12_09                   2  0.2546  Ocean plastic cleanup system passes key test
   7 q12_11                   2  0.2375  Ocean plastic cleanup system passes key tes...
   8 q12_23                   0  0.2231  Plastic packaging tax comes into force
   9 q12_21                   0  0.2133  Ocean plastic waste statistics revised down...
  10 q12_10                   1  0.1954  Plastic pollution

rank of relevant items (rel>=1): naive # -> BM25 core #
  q12_01                 rel=2  naive# 1  bm25#3
  q12_09                 rel=2  naive# 2  bm25#6
  q12_16                 rel=2  naive# 3  bm25#4
  q12_19                 rel=2  naive# 4  bm25#5
  q12_11                 rel=2  naive# 5  bm25#7
  q12_04                 rel=1  naive# 6  bm25#1
  q12_02                 rel=2  naive# 8  bm25#11
  q12_22                 rel=1  naive# 9  bm25#2
  q12_18                 rel=1  naive#12  bm25#17
  q12_03                 rel=2  naive#13  bm25#12
  q12_10                 rel=1  naive#14  bm25#10
  q12_12                 rel=1  naive#15  bm25#18
  q12_05                 rel=1  naive#16  bm25#16
  q12_06                 rel=1  naive#20  bm25#21
  q12_15                 rel=1  naive#23  bm25#23

harmful inversions (BM25 puts worse above better), top by rel gap: 11 total
  Cleanup technology startup pivots to river ... (rel 1) naive#9->bm25#2 [bm25 0.3259]
    pushed below Ocean plastic waste statistics revised down... (rel 0) naive#7->bm25#9 [bm25 0.2133]
  Ocean plastic cleanup system passes key tes... (rel 2) naive#5->bm25#7 [bm25 0.2375]
    pushed below Cleanup technology startup pivots to river ... (rel 1) naive#9->bm25#2 [bm25 0.3259]
  Ocean plastic cleanup system passes key tes... (rel 2) naive#5->bm25#7 [bm25 0.2375]
    pushed below Can technology really clean up the ocean? (rel 1) naive#6->bm25#1 [bm25 0.3846]
  Ocean plastic cleanup system passes key test (rel 2) naive#1->bm25#3 [bm25 0.2923]
    pushed below Cleanup technology startup pivots to river ... (rel 1) naive#9->bm25#2 [bm25 0.3259]
  Ocean plastic cleanup system passes key test (rel 2) naive#2->bm25#6 [bm25 0.2546]
    pushed below Cleanup technology startup pivots to river ... (rel 1) naive#9->bm25#2 [bm25 0.3259]
relevant items in top-10: naive=8 bm25=8

## q02_quantum_computing — 'quantum computing breakthrough'

items=23 relevance 0/1/2 = 6/10/7

query-term IDF (title field / description field):
  quantum                0.4372   1.1632
  computing              1.6740   2.7726
  breakthrough           2.7726   3.8712

top-10 naive:
   # id                     rel   score  title
   1 q02_04                   2  8.0000  Quantum computing
   2 q02_22                   1  6.0000  Breakthrough in computing energy efficiency...
   3 q02_21                   0  6.0000  Quantum computing stocks rally after earnings
   4 q02_23                   0  4.0000  Computing giant announces new data centres
   5 q02_13                   1  4.0000  Funding for quantum startups slows amid hyp...
   6 q02_19                   1  4.0000  How quantum computers could break RSA encry...
   7 q02_09                   1  4.0000  Quantum error correction
   8 q02_08                   1  3.0000  A beginner's guide to quantum error correction
   9 q02_17                   2  3.0000  Quantum error correction milestone is a ste...
  10 q02_12                   2  3.0000  Quantum error correction milestone reached,...

top-10 BM25 core:
   # id                     rel   score  title
   1 q02_22                   1  0.4270  Breakthrough in computing energy efficiency...
   2 q02_04                   2  0.4253  Quantum computing
   3 q02_23                   0  0.2025  Computing giant announces new data centres
   4 q02_21                   0  0.1873  Quantum computing stocks rally after earnings
   5 q02_09                   1  0.1000  Quantum error correction
   6 q02_13                   1  0.0901  Funding for quantum startups slows amid hyp...
   7 q02_19                   1  0.0858  How quantum computers could break RSA encry...
   8 q02_14                   1  0.0498  Superconducting qubits explained
   9 q02_07                   0  0.0461  Classical computers are still faster for mo...
  10 q02_05                   1  0.0388  What the new quantum result means for crypt...

rank of relevant items (rel>=1): naive # -> BM25 core #
  q02_04                 rel=2  naive# 1  bm25#2
  q02_22                 rel=1  naive# 2  bm25#1
  q02_13                 rel=1  naive# 5  bm25#6
  q02_19                 rel=1  naive# 6  bm25#7
  q02_09                 rel=1  naive# 7  bm25#5
  q02_08                 rel=1  naive# 8  bm25#15
  q02_17                 rel=2  naive# 9  bm25#17
  q02_12                 rel=2  naive#10  bm25#18
  q02_02                 rel=2  naive#11  bm25#14
  q02_01                 rel=2  naive#12  bm25#12
  q02_03                 rel=2  naive#13  bm25#11
  q02_11                 rel=2  naive#14  bm25#13
  q02_05                 rel=1  naive#15  bm25#10
  q02_06                 rel=1  naive#16  bm25#16
  q02_15                 rel=1  naive#17  bm25#19
  q02_14                 rel=1  naive#19  bm25#8
  q02_20                 rel=1  naive#20  bm25#22

harmful inversions (BM25 puts worse above better), top by rel gap: 1 total
  Quantum computing (rel 2) naive#1->bm25#2 [bm25 0.4253]
    pushed below Breakthrough in computing energy efficiency... (rel 1) naive#2->bm25#1 [bm25 0.4270]
relevant items in top-10: naive=8 bm25=7

## q01_ev_battery_recycling — 'electric vehicle battery recycling'

items=23 relevance 0/1/2 = 6/8/9

query-term IDF (title field / description field):
  electric               1.9253   2.2618
  vehicle                1.9253   3.8712
  battery                0.5754   1.3063
  recycling              0.7357   1.0380

top-10 naive:
   # id                     rel   score  title
   1 q01_04                   2 14.0000  Electric vehicle battery recycling
   2 q01_21                   0  9.0000  Electric vehicle battery warranty claims rise
   3 q01_19                   1  8.0000  r/technology thread: is battery recycling a...
   4 q01_17                   1  8.0000  Battery recycling
   5 q01_12                   2  7.0000  Battery recycling start-up raises $120m for...
   6 q01_20                   2  7.0000  Guardian analysis: EV battery recycling is ...
   7 q01_05                   1  7.0000  What happens to an EV battery when it dies?...
   8 q01_22                   1  6.0000  Battery recycling conference opens next week
   9 q01_01                   2  6.0000  How EV battery recycling is scaling across ...
  10 q01_02                   2  6.0000  How EV battery recycling is scaling across ...

top-10 BM25 core:
   # id                     rel   score  title
   1 q01_04                   2  0.6758  Electric vehicle battery recycling
   2 q01_21                   0  0.3952  Electric vehicle battery warranty claims rise
   3 q01_07                   0  0.2968  Sales of electric cars hit record high last...
   4 q01_17                   1  0.2753  Battery recycling
   5 q01_23                   0  0.2376  Vehicle recycling program expands for old cars
   6 q01_19                   1  0.2188  r/technology thread: is battery recycling a...
   7 q01_06                   1  0.1600  Recycling plant opening in my city — AMA ab...
   8 q01_20                   2  0.1507  Guardian analysis: EV battery recycling is ...
   9 q01_12                   2  0.1507  Battery recycling start-up raises $120m for...
  10 q01_05                   1  0.1448  What happens to an EV battery when it dies?...

rank of relevant items (rel>=1): naive # -> BM25 core #
  q01_04                 rel=2  naive# 1  bm25#1
  q01_19                 rel=1  naive# 3  bm25#6
  q01_17                 rel=1  naive# 4  bm25#4
  q01_12                 rel=2  naive# 5  bm25#9
  q01_20                 rel=2  naive# 6  bm25#8
  q01_05                 rel=1  naive# 7  bm25#10
  q01_22                 rel=1  naive# 8  bm25#12
  q01_01                 rel=2  naive# 9  bm25#13
  q01_02                 rel=2  naive#10  bm25#14
  q01_06                 rel=1  naive#13  bm25#7
  q01_03                 rel=2  naive#14  bm25#15
  q01_15                 rel=1  naive#15  bm25#11
  q01_09                 rel=1  naive#17  bm25#16
  q01_10                 rel=2  naive#18  bm25#19
  q01_11                 rel=2  naive#19  bm25#20
  q01_18                 rel=1  naive#21  bm25#22
  q01_13                 rel=2  naive#23  bm25#23

harmful inversions (BM25 puts worse above better), top by rel gap: 0 total
relevant items in top-10: naive=9 bm25=7

## Variant experiments (each measured independently; none substituted)

Variant (all with normalization & deterministic tie-break):
  variant                                P@5    P@10     MRR  nDCG@10
  naive baseline                      0.7875  0.8250  0.8958   0.6909
  bm25 core  (wt=2:1, b=0.75, smooth1)  0.6750  0.7438  0.8750   0.5674
  title-only (wt=1:0, b=0.75, smooth1)  0.7375  0.7875  0.9062   0.6263
  idf classic(wt=2:1, b=0.75)         0.6000  0.6687  0.8542   0.4750
  idf smooth2(wt=2:1, b=0.75)         0.6750  0.7438  0.8750   0.5735
  b=0.0      (wt=2:1, smooth1)        0.6750  0.7562  0.8646   0.5740
  b=0.5      (wt=2:1, smooth1)        0.6875  0.7438  0.8750   0.5701
  b=1.0      (wt=2:1, smooth1)        0.6750  0.7438  0.9062   0.5726
  desc-w 0.5 (wt=2:0.5, b=0.75, smooth1)  0.7000  0.7875  0.8750   0.6004
  desc-w 2.0 (wt=2:2, b=0.75, smooth1)  0.6500  0.6813  0.8958   0.5188

per-focus-query nDCG@10 by variant (core=wt2:1 b.75 smooth1):
  variant                               q13    q10    q12    q02    q01
  bm25 core  (wt=2:1, b=0.75, smooth1) 0.4453 0.6216 0.6719 0.3870 0.4795
  title-only (wt=1:0, b=0.75, smooth1) 0.6233 0.7505 0.7483 0.6221 0.5287
  idf classic(wt=2:1, b=0.75)        0.4453 0.2766 0.5964 0.3625 0.4260
  idf smooth2(wt=2:1, b=0.75)        0.4453 0.6216 0.7208 0.4494 0.4795
  b=0.0      (wt=2:1, smooth1)       0.4902 0.6400 0.7208 0.3857 0.4743
  b=0.5      (wt=2:1, smooth1)       0.4434 0.6437 0.7208 0.3870 0.4795
  b=1.0      (wt=2:1, smooth1)       0.4453 0.6528 0.6719 0.4494 0.4848
  desc-w 0.5 (wt=2:0.5, b=0.75, smooth1) 0.5210 0.6216 0.7238 0.5123 0.4811
  desc-w 2.0 (wt=2:2, b=0.75, smooth1) 0.5184 0.4326 0.4361 0.4494 0.4836
