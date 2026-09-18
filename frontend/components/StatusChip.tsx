const STYLES: Record<string, string> = {
  ACTIVE: "bg-active/10 text-active border-active/30",
  SUPERSEDED: "bg-superseded/10 text-superseded border-superseded/30",
  DISPUTED: "bg-disputed/10 text-disputed border-disputed/40",
  RETRACTED: "bg-retracted/10 text-retracted border-retracted/30",
  ENDED: "bg-ended/10 text-ended border-ended/30",
  ARCHIVED: "bg-muted/10 text-muted border-muted/30",
};

export default function StatusChip({ status }: { status: string }) {
  return (
    <span
      className={`inline-flex items-center border px-1.5 py-0.5 text-[10px] font-mono font-medium tracking-tight rounded ${
        STYLES[status] || STYLES.ARCHIVED
      }`}
    >
      {status.toLowerCase()}
    </span>
  );
}
