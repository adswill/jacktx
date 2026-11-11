import sys, array, math, cmath
# tone.py RATE F FILE...: power at exactly F (1 s blocks, averaged) against the median of nearby off-frequencies, dB
rate=int(sys.argv[1]); f0=float(sys.argv[2])
def p(x,f):
    n=rate; tot=0; nb=len(x)//n
    c=[math.cos(2*math.pi*f*i/rate) for i in range(n)]; s=[math.sin(2*math.pi*f*i/rate) for i in range(n)]
    for b in range(nb):
        seg=x[b*n:(b+1)*n]; re=sum(a*b_ for a,b_ in zip(seg,c)); im=sum(a*b_ for a,b_ in zip(seg,s)); tot+=re*re+im*im
    return tot/nb
for fn in sys.argv[3:]:
    x=array.array('f'); x.frombytes(open(fn,'rb').read())
    sig=p(x,f0); nb=sorted(p(x,f0+d) for d in (-23,-17,-11,-7,7,11,17,23)); med=(nb[3]+nb[4])/2
    print("  %-22s tone at %.1f Hz: %+6.1f dB over nearby noise (noise spread %.1f dB)"%(fn,f0,10*math.log10(sig/med),10*math.log10(nb[-1]/nb[0])))
