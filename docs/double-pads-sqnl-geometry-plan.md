# DoublePadsSQNL Qubit Geometry 확정 PLAN

## 목표

- Target qubit frequency: `f01 = 5 GHz`
- Target ratio: `EJ/EC = 70`
- Derived targets:
  - `EC / h = 220.6 MHz`
  - `EJ / h = 15.44 GHz`
  - `CΣ = 87.8 fF`
  - `Ic = 31.1 nA`
  - Anharmonicity: `alpha ≈ -220.6 MHz`

따라서 geometry 확정 문제는 `DoublePadsSQNL`의 effective total capacitance를 `CΣ ≈ 88 fF`로 맞추는 문제로 둔다.

## 현재 Geometry Contract

- Physical junction은 `SqnlManhattanSingleJunctionV2`를 사용한다.
- Contact pad는 사용하지 않는다.
- `base_metal_addition` layer는 physical V2 junction에서 사용하지 않는다.
- Junction metal은 실제 lead/finger region만 사용한다.
- Qubit taper는 junction lead 끝점에 직접 연결한다.

Direct attach 기준 refpoint:

- `attach_island_1`: upper junction lead outer end
- `attach_island_2`: lower junction lead outer end
- `origin_squid = attach_island_2`
- `port_common = attach_island_1`

`DoublePadsSQNL`에서는 transformed debug refpoint로 다음을 확인한다.

- `junction_attach_island_1`
- `junction_attach_island_2`

기본 V2 direct lead attach span은 약 `7.428 um`이다.

## KQCircuits 예제에서 가져올 Simulation Workflow

참고 예제:

- `KQCircuits/klayout_package/python/scripts/simulations/double_pads_sim.py`
- `KQCircuits/klayout_package/python/scripts/simulations/double_pads_epr_sim.py`
- `KQCircuits/klayout_package/python/kqcircuits/simulations/single_element_simulation.py`
- `KQCircuits/klayout_package/python/kqcircuits/simulations/epr/double_pads.py`

KQCircuits의 핵심 패턴:

1. Full-chip simulation 전에 single-element qubit simulation을 먼저 만든다.
2. Microscopic junction geometry를 EM simulation에 그대로 넣기보다 `Sim` junction surrogate를 사용한다.
3. Geometry sweep으로 capacitance target을 맞춘다.
4. 후보 geometry에 대해 eigenmode/EPR/loss simulation을 수행한다.
5. 마지막에 full-chip smoke/readout simulation으로 integration을 확인한다.

## SCDevice에 필요한 Simulation 구조

### 1. Single-element `DoublePadsSQNL` simulation

`get_single_element_sim_class(DoublePadsSQNL, ...)` 패턴을 사용해 단일 qubit simulation script를 만든다.

이 script는 full-chip이 아니라 `DoublePadsSQNL` 하나만 배치하고 capacitance/eigenmode solver에 넘기는 용도다.

필수 조건:

- V2 physical attach span과 simulation attach span이 같아야 한다.
- Taper endpoint가 simulation junction refpoint와 같은 위치에 있어야 한다.
- `junction_attach_island_1/2`를 export/debug 가능한 refpoint로 유지한다.

### 2. Simulation junction surrogate 선택

#### Option A: KQ `Sim` junction 사용

- `junction_total_length`를 V2 direct lead span인 약 `7.428 um`에 맞춘다.
- 빠르게 capacitance sweep을 시작할 수 있다.
- 단점: KQ `Sim`은 `base_metal_addition` pad를 생성하므로 physical no-pad contract와 다르다.

#### Option B: SCDevice no-pad direct-lead sim junction 추가

권장 방향.

새 simulation junction은 다음 refpoint contract만 제공하고 pad/addition metal은 만들지 않는다.

- `origin_squid`
- `port_common`
- `port_squid_a`
- `port_squid_b`
- `attach_island_1`
- `attach_island_2`

이렇게 하면 physical V2와 simulation surrogate가 같은 direct lead attach 기준을 공유한다.

## Sweep 대상 Parameter

Capacitance target `CΣ ≈ 88 fF`를 맞추기 위해 우선 sweep할 parameter:

- `island_island_gap`
- upper/lower island extent
- `island1_taper_width`
- `island2_taper_width`
- `island1_taper_junction_width`
- `island2_taper_junction_width`
- `coupler_extent`
- `coupler_offset`
- `coupler_a`
- `ground_gap`

Sweep 중 반드시 같이 확인할 항목:

- direct lead attach span 보존 여부
- taper angle
- taper throat minimum width
- island-to-island clearance
- fab minimum width/gap rule
- coupler capacitance 변화량

## Capacitance Simulation 목표

단일 qubit capacitance simulation에서 target은:

```text
CΣ_target = 87.8 fF
```

후보 geometry는 capacitance matrix에서 effective qubit capacitance가 `88 fF` 근처인 조합으로 고른다.

후보별로 다음 식으로 frequency를 재계산한다.

```text
f01 = (sqrt(8 * EJ / EC) - 1) * EC / h
EC = e^2 / (2 * CΣ)
EJ / EC = 70
```

Accept range는 초기에 `f01 = 5.0 GHz ± 100 MHz` 정도로 두고, fabrication/junction uncertainty까지 반영한 뒤 좁힌다.

## Eigenmode / EPR Workflow

Capacitance sweep으로 후보를 좁힌 뒤 다음을 수행한다.

1. Eigenmode simulation으로 qubit mode frequency 확인
2. EPR simulation으로 participation 확인
3. Cross-section correction simulation으로 thin layer/loss correction 반영

기존 KQ `epr/double_pads.py`는 vanilla `DoublePads`의 vertical junction/taper 가정을 사용한다.

`DoublePadsSQNL`에서는 EPR partition을 새로 정의해야 한다.

Partition 기준:

- upper island region
- lower island region
- direct junction lead/taper throat region
- coupler region
- substrate/metal interface region

특히 junction 근처 partition은 `junction_attach_island_1/2` refpoint를 기준으로 잡는다.

## Full-chip Simulation 위치

`sqnl_full_chip_sim.py --smoke-check`는 geometry 확정용 1차 simulation이 아니다.

역할:

- single-qubit geometry가 full-chip layout에 들어갔을 때 깨지지 않는지 확인
- readout/feedline port wiring이 유지되는지 확인
- `junction_type="Sim"` fallback path가 계속 호환되는지 확인

따라서 full-chip simulation은 single-element capacitance/eigenmode/EPR 후보가 나온 뒤 수행한다.

## Acceptance Criteria

Geometry를 확정하려면 다음 조건을 만족해야 한다.

### Layout

- V2 junction에 contact pad가 없다.
- V2 junction에 `base_metal_addition` shape가 없다.
- Actual junction metal은 `SIS_junction_2`에만 있다.
- Upper/lower qubit taper가 각각 V2 lead end에 직접 닿는다.
- `junction_attach_island_1/2`가 `x=0` centerline에 정렬된다.
- 두 attach point midpoint가 `squid_offset`과 일치한다.

### Capacitance

- Effective `CΣ`가 `87.8 fF` 근처다.
- 계산된 `f01`이 `5 GHz` 근처다.
- Coupler capacitance가 readout 설계 target과 양립한다.

### Fabrication

- Minimum width/gap rule을 만족한다.
- Taper throat가 너무 좁지 않다.
- Taper angle이 과도하지 않다.
- Junction lead와 taper 연결부에 unintended notch/gap/overlap artifact가 없다.

### EPR / Loss

- Direct lead/taper throat 주변 participation이 과도하지 않다.
- Metal-substrate/interface participation이 후보 간 비교 가능한 수준으로 정리된다.
- Cross-section correction 후에도 후보 순위가 유지된다.

### Integration

- `DoublePadsSQNL` V2 build가 성공한다.
- `DoublePadsSQNL` simulation surrogate build가 성공한다.
- `junction_type="Sim"` fallback build가 성공한다.
- `sqnl_full_chip_sim.py --smoke-check`가 성공한다.

## 실행 순서

1. V2 direct lead geometry OAS/GDS 시각 확인
2. `DoublePadsSQNL` single-element capacitance simulation script 작성
3. Simulation junction surrogate 결정
   - short-term: KQ `Sim` span 보정
   - preferred: SCDevice no-pad direct-lead sim junction
4. `CΣ ≈ 88 fF`를 target으로 geometry sweep 실행
5. 후보 geometry별 `f01`, `EC`, `EJ`, `Ic` 계산
6. 후보 2-3개에 대해 eigenmode simulation 실행
7. `DoublePadsSQNL`용 EPR partition 구현
8. EPR/loss/cross-section correction 실행
9. 최종 geometry를 PCell default 또는 simulation preset으로 반영
10. Full-chip smoke/readout integration 확인

## 아직 정해야 할 입력값

- Readout coupling capacitance target
- Fabrication minimum width/gap
- 허용 taper angle 또는 taper length constraint
- Junction process 기준 `Ic` 또는 critical current density
- Simulation에서도 `base_metal_addition`을 완전히 금지할지 여부

