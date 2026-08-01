import { useEffect, useState } from "react";
import {
  isCsrfReady,
  isLocalSessionMode,
  subscribeCsrfReady,
} from "./csrfManager";

/** Estado de preparación CSRF para deshabilitar botones mutables. */
export function useCsrfReady(): {
  csrfReady: boolean;
  csrfPreparing: boolean;
} {
  const [csrfReady, setCsrfReady] = useState(isCsrfReady);

  useEffect(() => {
    setCsrfReady(isCsrfReady());
    return subscribeCsrfReady(() => {
      setCsrfReady(isCsrfReady());
    });
  }, []);

  return {
    csrfReady,
    csrfPreparing: isLocalSessionMode() && !csrfReady,
  };
}
