import { describe, expect, it } from 'vitest';
import { Err, Ok } from './Result';
import { Registry } from './Registry';
import { DisposableStore } from './Disposable';
import { EventBus } from './EventBus';

describe('Result', () => {
  it('Ok carries a value and Err carries an error', () => {
    const good = Ok(41);
    const bad = Err('nope');
    expect(good.ok && good.value).toBe(41);
    expect(!bad.ok && bad.error).toBe('nope');
  });
});

describe('Registry', () => {
  type Entry = { id: string; label: string };
  it('register/get/require/upsert/unregister lifecycle', () => {
    const registry = new Registry<Entry>('things');
    registry.register({ id: 'a', label: 'A' });
    expect(registry.get('a')?.label).toBe('A');
    expect(() => registry.register({ id: 'a', label: 'again' })).toThrow();
    registry.upsert({ id: 'a', label: 'A2' });
    expect(registry.require('a').label).toBe('A2');
    expect(registry.has('a')).toBe(true);
    registry.unregister('a');
    expect(registry.get('a')).toBeUndefined();
    expect(() => registry.require('a')).toThrow(/unknown id/);
  });
});

describe('DisposableStore', () => {
  it('disposes everything it holds exactly once', () => {
    const store = new DisposableStore();
    let calls = 0;
    store.add({ dispose: () => (calls += 1) });
    store.add({ dispose: () => (calls += 1) });
    store.dispose();
    store.dispose();
    expect(calls).toBe(2);
  });
});

describe('EventBus', () => {
  it('on/off and onAny deliver and detach', () => {
    const bus = new EventBus<{ ping: { n: number } }>();
    const seen: number[] = [];
    const off = bus.on('ping', (p) => seen.push(p.n));
    let anyCount = 0;
    const offAny = bus.onAny(() => (anyCount += 1));
    bus.emit('ping', { n: 1 });
    off();
    bus.emit('ping', { n: 2 });
    offAny();
    bus.emit('ping', { n: 3 });
    expect(seen).toEqual([1]);
    expect(anyCount).toBe(2);
  });
});
