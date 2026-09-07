import { useEffect, useState } from 'react';

/**
 * The window's current width, re-rendering the caller when it changes.
 *
 * A hook rather than a media query because the question the shell asks is
 * arithmetic — see `panelsMustOverlay`. CSS can express "narrower than 1100px";
 * it cannot express "narrower than the panels that happen to be open".
 */
export function useViewportWidth(): number {
  const [width, setWidth] = useState(() => window.innerWidth);

  useEffect(() => {
    const onResize = () => setWidth(window.innerWidth);
    window.addEventListener('resize', onResize);
    // Read once on mount too: the window can be resized between the first
    // render and this effect (a restored session, a devtools dock).
    onResize();
    return () => window.removeEventListener('resize', onResize);
  }, []);

  return width;
}
