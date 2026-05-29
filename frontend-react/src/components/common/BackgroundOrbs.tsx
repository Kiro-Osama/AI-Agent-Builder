export function BackgroundOrbs() {
  return (
    <div className="pointer-events-none fixed inset-0 z-0 overflow-hidden">
      <div className="absolute -right-[200px] -top-[200px] h-[600px] w-[600px] rounded-full bg-ab-purple opacity-15 blur-[120px] animate-float-1" />
      <div className="absolute -bottom-[150px] -left-[150px] h-[500px] w-[500px] rounded-full bg-ab-blue opacity-15 blur-[120px] animate-float-2" />
      <div className="absolute left-1/2 top-[40%] h-[400px] w-[400px] rounded-full bg-ab-cyan opacity-10 blur-[120px] animate-float-3" />
    </div>
  )
}
