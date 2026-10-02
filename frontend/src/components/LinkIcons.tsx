/** Íconos decorativos para enlaces de tarjeta (el texto o aria-label da el nombre). */
const svgProps = {
  className: "card-link-icon",
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.75,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  focusable: "false" as const,
  "aria-hidden": true,
};

export function FolderLinkIcon() {
  return (
    <svg {...svgProps}>
      <path d="M3.75 6.75A1.5 1.5 0 0 1 5.25 5.25h4.1l1.9 2.25h7.5a1.5 1.5 0 0 1 1.5 1.5v8.25a1.5 1.5 0 0 1-1.5 1.5H5.25a1.5 1.5 0 0 1-1.5-1.5Z" />
    </svg>
  );
}

export function ExternalLinkIcon() {
  return (
    <svg {...svgProps}>
      <path d="M14 4.5h5.5V10" />
      <path d="M19.5 4.5 11 13" />
      <path d="M17.5 13.5v4.25a1.75 1.75 0 0 1-1.75 1.75H6.25a1.75 1.75 0 0 1-1.75-1.75V8.25A1.75 1.75 0 0 1 6.25 6.5h4.25" />
    </svg>
  );
}
