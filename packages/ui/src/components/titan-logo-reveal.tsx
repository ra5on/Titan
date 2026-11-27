import {motion, useReducedMotion} from 'motion/react'
import {useEffect} from 'react'

import TitanLogo from '@/components/titan-logo'

export function TitanLogoReveal({
	className,
	delay,
	onComplete,
}: {
	className?: string
	delay: number
	onComplete: () => void
}) {
	const reduceMotion = useReducedMotion()

	useEffect(() => {
		if (reduceMotion) onComplete()
	}, [onComplete, reduceMotion])

	if (reduceMotion) return <TitanLogo className={className} opacity={0.85} />

	return (
		<motion.div
			initial={{clipPath: 'inset(0 0 100% 0)', opacity: 0}}
			animate={{clipPath: 'inset(0 0 0 0)', opacity: 0.85}}
			transition={{delay, duration: 1.2, ease: [0.16, 1, 0.3, 1]}}
			onAnimationComplete={onComplete}
		>
			<TitanLogo className={className} />
		</motion.div>
	)
}
