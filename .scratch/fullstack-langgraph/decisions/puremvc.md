# Decision: PureMVC as a framework — rejected

Status: resolved
Type: grilling
Date: 2026-08-04

## Question

Should the platform adopt PureMVC (the framework) across the TypeScript editor and the Python runtime, given the stated preference for "pure MVC"? Does it create overhead or become a bottleneck?

## Answer

**Reject PureMVC the framework. Keep the MVC layering discipline already in place.**

### It is maintained, but frozen

Corrected an initial assumption: the [TypeScript multicore port](https://www.npmjs.com/package/@puremvc/puremvc-typescript-multicore-framework) is actively published (v2.1.2, Aug 2026). But [PureMVC is "stable and feature-frozen since 2008"](https://puremvc.org/) and the [Python ports carry 2006–2012 headers](https://github.com/PureMVC/puremvc-python-multicore-framework). It is maintained, not evolving. Age alone is not the argument — the following four are.

### 1. String-keyed notifications discard the type system

PureMVC decouples via `sendNotification(name, body?, type?)` with an untyped body. The existing `EventBus<WorkflowEvents>` is typed end to end, and Pydantic's entire value is validated shapes. Routing every domain event through an untyped body and re-validating per handler is a strict downgrade in *both* languages — and it is the one thing the destination explicitly depends on (generated types, no drift).

### 2. Mediator-per-component is the wrong shape for a canvas — reproduced, not theorised

PureMVC expects one `Mediator` per view component, each string-matching notifications. Phase 1's first `useNode` did the coarse equivalent (subscribe to all model events) and **exceeded React's update-depth limit with six nodes on screen**, because every card re-renders and every card measures itself on render. The fix was the opposite of the Mediator model: one `NodeLayer` owning all portals, plus per-node subscriptions filtered by `nodeId`. At the target scale (hundreds of nodes) the Mediator pattern is a re-render storm by construction.

### 3. A PureMVC Command is not an undoable Command

PureMVC `SimpleCommand`/`MacroCommand` are notification handlers — fire-and-forget, no `undo`. The editor's `ICommand` has `execute`/`undo` plus coalescing, and it is what makes undo generic across every feature. Conflating the two names would cost the undo stack outright. This is the most expensive mistake available here.

### 4. In Python, LangGraph already *is* the architecture

`StateGraph` + node functions + reducers + checkpointers already dictate control flow and state ownership. Layering PureMVC on top yields two orchestrators competing for the same responsibility. LangGraph nodes are also *functions*, not classes with Mediators — the models do not compose.

### What is kept

The separation PureMVC advocates — model owns state, view renders, commands mutate — is correct and already implemented without the dependency. `core/` imports neither React nor JointJS; the canvas is a one-way projection of the model; every mutation is an `ICommand`. That is the value; the framework is not required to obtain it.

### Consequence for the entity hierarchy

Rejecting PureMVC does **not** weaken the `IEntity → Base* → concrete` requirement — that is inheritance in the domain model, which is orthogonal to PureMVC's Facade/Proxy/Mediator triad. See ticket `08-entity-hierarchy`.
