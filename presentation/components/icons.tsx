interface IconProperties {
  className?: string;
}

export function ArrowIcon({ className }: IconProperties) {
  return <svg className={className} aria-hidden="true" viewBox="0 0 20 20"><path d="M4 10h11M11 6l4 4-4 4" /></svg>;
}

export function ReturnIcon({ className }: IconProperties) {
  return <svg className={className} aria-hidden="true" viewBox="0 0 24 24"><path d="M9 7H5v4M5.5 10.5A7.5 7.5 0 1 0 8 5.3" /></svg>;
}

export function OrderIcon({ className }: IconProperties) {
  return <svg className={className} aria-hidden="true" viewBox="0 0 24 24"><path d="M5 7.5 12 4l7 3.5v9L12 20l-7-3.5zM5 7.5l7 3.5 7-3.5M12 11v9" /></svg>;
}

export function PulseIcon({ className }: IconProperties) {
  return <svg className={className} aria-hidden="true" viewBox="0 0 24 24"><path d="M3 12h4l2-5 4 10 2.2-5H21" /></svg>;
}

export function ShieldIcon({ className }: IconProperties) {
  return <svg className={className} aria-hidden="true" viewBox="0 0 24 24"><path d="M12 3.5 19 6v5.2c0 4.4-2.8 7.4-7 9.3-4.2-1.9-7-4.9-7-9.3V6zM8.5 12l2.2 2.2 4.8-5" /></svg>;
}

export function CheckIcon({ className }: IconProperties) {
  return <svg className={className} aria-hidden="true" viewBox="0 0 20 20"><path d="m4.5 10 3.3 3.4 7.7-7.3" /></svg>;
}

export function DatabaseIcon({ className }: IconProperties) {
  return <svg className={className} aria-hidden="true" viewBox="0 0 24 24"><ellipse cx="12" cy="6" rx="7" ry="3"/><path d="M5 6v6c0 1.7 3.1 3 7 3s7-1.3 7-3V6M5 12v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6" /></svg>;
}
