import type {SVGProps} from 'react'

export default function TitanLogo(props: SVGProps<SVGSVGElement>) {
	return (
		<svg xmlns='http://www.w3.org/2000/svg' width={64} viewBox='0 0 96 96' color='#CBD7F0' aria-hidden {...props}>
			<path fill='currentColor' d='M7 14H65C54 19 45 27 39 38H7Z M83 14H89V38H72C64 38 60 43 60 51V79Q60 84 55 84H36V61C36 37 52 20 83 14Z' />
		</svg>
	)
}
