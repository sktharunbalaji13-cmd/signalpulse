type SourceChipProps = {
  sourceType: string
}

export function SourceChip({ sourceType }: SourceChipProps) {
  return <span className={`chip chip--${sourceType}`}>{sourceType.toUpperCase()}</span>
}