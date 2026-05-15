# Spike-Circuit Correspondence

> **Claim.** The names *spike* and *circuit* in Spikuit are not metaphorical. They refer to computationally well-defined operations on a single object — the synapse weight matrix — whose equilibria, spectral modes, and energy minima admit direct interpretation in the terminology of neural dynamics and associative memory.

This appendix formalises the mathematical correspondence that underwrites Spikuit's design. It ties together material from [Computational Neuroscience](neuroscience.md), [Knowledge Graphs](graph.md), and [Information Retrieval](retrieval.md) by showing that *spike propagation*, *retrieval*, and *memory modes* are three readings of the same linear algebra.

---

## 1. Setup

Let $G = (N, S, W)$ be the knowledge graph, where:

- $N = \{n_1, \dots, n_n\}$ is the set of Neurons.
- $S \subseteq N \times N$ is the set of Synapses.
- $W \in \mathbb{R}_{\ge 0}^{n \times n}$ is the synapse weight matrix (possibly asymmetric; directed Synapses).

Derived quantities:

- Degree matrix $D = \operatorname{diag}(d_1, \dots, d_n)$ with $d_i = \sum_j W_{ij}$.
- Random-walk transition $\tilde{A} = D^{-1} W$.
- Symmetrised adjacency $W_{\mathrm{sym}} = \tfrac{1}{2}(W + W^\top)$.
- Symmetric normalised Laplacian $L_{\mathrm{sym}} = I - D^{-1/2} W_{\mathrm{sym}} D^{-1/2}$.

We will interpret three operations on $W$:

| Operation | What it produces | Spikuit feature |
|---|---|---|
| Power iteration on $\tilde{A}$ | Fixed-point activation distribution | `centrality` |
| Gradient descent on an energy $E(s; W)$ | Locally stable configurations | `retrieve` |
| Eigendecomposition of $L_{\mathrm{sym}}$ | Basis of "memory modes" | `eigentheme profile` (proposed) |

---

## 2. Spike Propagation as Power Iteration

Spikuit's spike propagation uses [APPNP](graph.md) (Approximate Personalized PageRank). Starting from an initial activation $x_0 \in \mathbb{R}_{\ge 0}^n$, the update is

$$
x_{t+1} = (1 - \alpha)\, \tilde{A}\, x_t + \alpha\, x_0, \qquad \alpha \in (0, 1).
$$

### 2.1 Fixed point

$\tilde{A}$ is a row-stochastic matrix, hence a contraction toward the leading eigenspace. Setting $x_{t+1} = x_t = x_\infty$ yields

$$
x_\infty = \alpha \big(I - (1 - \alpha)\tilde{A}\big)^{-1} x_0.
$$

This is the **personalized PageRank vector** seeded at $x_0$ (Page et al., 1999; Gasteiger et al., 2019).

### 2.2 Centrality as the untethered limit

Dropping the teleport term ($\alpha \to 0^+$) gives pure random-walk propagation. By the Perron–Frobenius theorem (for a strongly connected graph), $\tilde{A}$ has a unique positive left eigenvector $v^*$ with eigenvalue $1$, and for any $x_0 > 0$,

$$
\lim_{t \to \infty} \frac{x_t}{\|x_t\|_1} = v^*.
$$

Equivalently, $v^*$ solves $v^* = \tilde{A}^\top v^*$. This is exactly **eigenvector centrality** (the PageRank vector in its untethered form).

### 2.3 Interpretation

> **Eigenvector centrality = the steady-state firing frequency of the circuit under persistent, unbiased stimulation.**

The scalar `centrality` that Spikuit currently mixes into [hybrid retrieval](retrieval.md) is the stationary point of the spike propagation dynamics. The name *spike* is therefore not decorative: `neuron fire` is the one-step operator whose $t \to \infty$ limit is precisely this scalar.

---

## 3. Retrieval as Hopfield-Style Associative Recall

Let $s \in [0, 1]^n$ denote a state vector over Neurons, and define the energy

$$
E(s;\, W, b) = -\tfrac{1}{2}\, s^\top W_{\mathrm{sym}}\, s + b^\top s,
$$

with bias $b \in \mathbb{R}^n$ encoding per-Neuron intrinsic activation cost (e.g. inverse retrievability, inverse pressure).

This is the Hopfield energy (Hopfield, 1982) specialised to the Spikuit graph. Under asynchronous gradient descent

$$
\dot{s}_i = -\frac{\partial E}{\partial s_i} = (W_{\mathrm{sym}} s)_i - b_i,
$$

states evolve toward local minima — basins of attraction that Hopfield identified with stored memories.

### 3.1 Query as initial condition

A retrieval query $q$ is encoded as an initial state $s_0 = \iota(q)$ (e.g. a thin activation over Neurons whose text or embedding matches $q$). The retrieval result is the local minimum $s_\infty$ reached by descent from $s_0$.

### 3.2 Basin structure and the spectrum

The Hessian of $E$ is $-W_{\mathrm{sym}}$. Local basin geometry (which Neurons co-activate, how sharply) is governed by the eigenvalues of $W_{\mathrm{sym}}$, or equivalently by the small eigenvalues of $L_{\mathrm{sym}}$.

### 3.3 Interpretation

> **Retrieval is gradient descent in an energy landscape whose curvature is the graph spectrum.**

The hybrid retrieval score in [retrieval.md](retrieval.md) is not an ad-hoc weighted sum. Each term corresponds to a different component of the underlying Hopfield dynamics:

| Score term | Dynamical role |
|---|---|
| `semantic_sim`, `keyword_sim` | Query encoding $\iota(q) \to s_0$ |
| `centrality` | Global bias from eigenspectrum |
| `pressure` (LIF) | Time-varying bias $b(t)$ |
| `retrievability` (FSRS) | Per-Neuron cost modulation |
| `feedback_boost` | Persistent query-conditioned bias |

---

## 4. Memory Modes as Laplacian Eigenvectors

Let $L_{\mathrm{sym}} = U \Lambda U^\top$ with $\Lambda = \operatorname{diag}(\lambda_1, \dots, \lambda_n)$ and $0 = \lambda_1 \le \lambda_2 \le \dots \le \lambda_n \le 2$.

The columns of $U$ form the **graph Fourier basis** (Shuman et al., 2013). Small-$\lambda$ eigenvectors vary slowly across the graph and capture coarse structure; large-$\lambda$ eigenvectors oscillate rapidly and capture local detail.

### 4.1 Eigenthemes

For a chosen rank $k$, define the **eigentheme embedding**

$$
\phi: N \to \mathbb{R}^k, \qquad \phi(n_i) = (U_{i, 2}, U_{i, 3}, \dots, U_{i, k+1}).
$$

(The trivial mode $u_1$ is skipped; it is constant and carries no information.)

Each Neuron is represented as a point in $\mathbb{R}^k$ whose axes correspond to the dominant semantic themes implicit in the graph's connectivity — not to externally declared tags or domains.

### 4.2 Connection to community structure

Spectral clustering (Shi & Malik, 2000; Ng et al., 2001) is a well-known consequence: the first $k$ non-trivial eigenvectors of $L_{\mathrm{sym}}$, when fed to $k$-means, recover approximately the same partition as modularity-based community detection on graphs with clear block structure.

In Spikuit, `community` is defined as the *hard quantisation* of $\phi$: two Neurons share a community iff their top-$k$ eigentheme coordinates place them on the same side of a gap-ratio threshold. Earlier versions implemented community detection via the Louvain algorithm (Blondel et al., 2008); from v0.8.3 onward this is replaced by spectral clustering on $\phi$, eliminating one independent classification mechanism (see §6.2 below).

### 4.3 Connection to synchronisation dynamics

On a graph of coupled oscillators (Kuramoto, 1984), the eigenvalues of $L_{\mathrm{sym}}$ determine which subsets of nodes synchronise in which frequency bands. The same mathematics governs resting-state networks in fMRI (Huang et al., 2018). In Spikuit:

> **Eigenthemes describe which Neurons tend to be co-activated when the circuit settles into a natural mode.**

This is the content of saying that the graph has *themes* at all: a theme is a collection of Neurons that the dynamics treat as a single unit.

---

## 5. The Unified Picture

All three interpretations reduce to operations on one matrix, $W$:

$$
\underbrace{v^* : \tilde{A}^\top v^* = v^*}_{\text{centrality (dynamics)}} \qquad
\underbrace{s_\infty : \nabla E(s_\infty; W) = 0}_{\text{retrieval (energy)}} \qquad
\underbrace{U : L_{\mathrm{sym}} U = U \Lambda}_{\text{themes (spectrum)}}
$$

- **Centrality** is the $t \to \infty$ limit of a one-step dynamical operator.
- **Retrieval** is the $t \to \infty$ limit of a gradient-descent operator on a scalar energy.
- **Eigenthemes** are the diagonalising basis of a static spectral operator.

The first two are *dynamical* readings (fixed points of iterative processes); the third is a *structural* reading (decomposition of an operator). Spikuit's design exposes all three: `neuron fire` drives the dynamics, `retrieve` performs the energy descent, and (proposed, v0.8.3+) `eigentheme profile` exposes the structural basis.

### 5.1 Why the same matrix

There is no coincidence: the matrix $W$ encodes what it means for two pieces of knowledge to be *related*, and every subsequent construction — flow, energy, curvature — is a consistency statement on that single relation.

### 5.2 Consequences for design

- **Retrieval scores have a theoretical derivation, not only an empirical tuning.** Each weighted term in the hybrid score reflects a distinct aspect of the same underlying operator.
- **Audit and visualisation share a mathematical substrate.** Both `domain audit --theme-drift` and `visualize --layout structural` consume $\phi$.
- **Centrality, eigentheme, community are not independent features.** They are different projections of the same spectral object, and upgrading `centrality` from a scalar to a vector (eigentheme profile) is a refinement in dimension, not a change of algorithm.

---

## 6. Practical Consequences

1. **Centrality is theoretically a projection onto the Perron eigenvector.** The current scalar centrality is the rank-1 case of a more general spectral construction.
2. **Eigenthemes generalise communities.** A Neuron's participation in a community is the thresholded projection of its eigentheme coordinates; keeping the continuous version preserves strictly more information.
3. **Retrieval scoring is a consistent aggregation, not a heuristic.** Each additive term answers a different question about the same operator $W$ applied to the same query-encoded state.
4. **Spike-circuit language is literal.** *Spikes* are the dynamics (`fire`, APPNP), *circuits* are the structure (graph Laplacian). Both reduce to linear algebra on $W$.

### 6.2 Classification minimalism

Consequence 2 has an architectural implication: Spikuit's knowledge graph requires exactly two classification mechanisms, not three.

- **`domain`** — user-declared, discrete, single-assignment, **nullable**. Exogenous to $W$; the user's own taxonomy.
- **`eigentheme` / `community`** — spectrally derived, two readings of $\phi$. The continuous reading (`eigentheme`) feeds retrieval; the discrete reading (`community`) is a hard quantisation used for auditing and reporting.

A separate modularity-based `community` mechanism (e.g. Louvain) is redundant: for graphs with clear block structure, spectral clustering on $\phi$ and modularity maximisation converge to approximately the same partition (Newman, 2006; von Luxburg, 2007). Running both adds an algorithmic dependency without adding information. Spikuit therefore retains the name `community` but binds it to the spectral construction, reducing the number of independent classification algorithms from three to one.

This minimalism has two concrete payoffs. First, `domain audit` becomes a single comparison: user-declared `domain` against the emergent `community` induced by $\phi$, rather than a three-way reconciliation. Second, null `domain` values can be auto-filled by the majority `domain` inside the containing `community`, with ambiguous cases surfaced for user review — a natural consequence of using the same operator for both membership and curation.

---

## 7. References

### Graph spectral theory
- Shi, J. & Malik, J. (2000). Normalized cuts and image segmentation. *IEEE PAMI*, 22(8), 888–905.
- Ng, A. Y., Jordan, M. I. & Weiss, Y. (2001). On spectral clustering: Analysis and an algorithm. *NeurIPS 2001*.
- Shuman, D. I., Narang, S. K., Frossard, P., Ortega, A. & Vandergheynst, P. (2013). The emerging field of signal processing on graphs. *IEEE Signal Processing Magazine*, 30(3), 83–98.
- von Luxburg, U. (2007). A tutorial on spectral clustering. *Statistics and Computing*, 17(4), 395–416.
- Newman, M. E. J. (2006). Modularity and community structure in networks. *PNAS*, 103(23), 8577–8582.
- Blondel, V. D., Guillaume, J.-L., Lambiotte, R. & Lefebvre, E. (2008). Fast unfolding of communities in large networks. *Journal of Statistical Mechanics*, 2008(10), P10008.

### Dynamics
- Page, L., Brin, S., Motwani, R. & Winograd, T. (1999). The PageRank citation ranking. *Stanford InfoLab*.
- Gasteiger, J., Bojchevski, A. & Günnemann, S. (2019). Predict then Propagate: GNNs meet Personalized PageRank. *ICLR 2019*.
- Perron, O. (1907). Zur Theorie der Matrices. *Mathematische Annalen*, 64, 248–263.

### Associative memory
- Hopfield, J. J. (1982). Neural networks and physical systems with emergent collective computational abilities. *PNAS*, 79(8), 2554–2558.
- Amit, D. J. (1989). *Modeling Brain Function: The World of Attractor Neural Networks*. Cambridge University Press.

### Neural synchronisation & neuroimaging
- Kuramoto, Y. (1984). *Chemical Oscillations, Waves, and Turbulence*. Springer.
- Huang, H., Ding, M. et al. (2018). Spectral graph theory in neuroimaging. *NeuroImage*, 179, 117–129.

---

## 8. Notes for Future Work

- **Empirical validation (Paper 1, cs.IR).** Ablations on BEIR/SciDocs measuring the contribution of each score term to nDCG/MRR. Centrality vs eigentheme-profile retrieval as separate conditions.
- **Theoretical paper (candidate, cs.LG or q-bio.NC).** Formalisation of the correspondence above, with convergence bounds and the specific Hopfield encoding chosen for Spikuit. Publication structure to be decided after daily-use validation.
- **Directed graphs.** The current presentation symmetrises $W$ for spectral analysis. Extension to directed Synapses uses the Magnetic Laplacian (Furutani et al., 2020) or the SVD of $W$; implementation choice deferred.
- **Time-varying weights.** STDP updates $W$ continuously. The framework applies per snapshot, but a continuous-time version (graph-Laplacian ODEs) is a natural next step.
