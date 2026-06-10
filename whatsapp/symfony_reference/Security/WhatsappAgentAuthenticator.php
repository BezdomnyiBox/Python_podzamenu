<?php

declare(strict_types=1);

namespace App\Security;

use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\HttpFoundation\Response;
use Symfony\Component\Security\Core\Authentication\Token\TokenInterface;
use Symfony\Component\Security\Core\Exception\AuthenticationException;
use Symfony\Component\Security\Http\Authenticator\AbstractAuthenticator;
use Symfony\Component\Security\Http\Authenticator\Passport\Badge\UserBadge;
use Symfony\Component\Security\Http\Authenticator\Passport\Passport;
use Symfony\Component\Security\Http\Authenticator\Passport\SelfValidatingPassport;

/**
 * Bearer-токен для офисного WhatsApp-агента.
 *
 * В services.yaml / .env:
 *   WHATSAPP_AGENT_TOKEN=секрет
 *   WHATSAPP_AGENT_ID=office-main
 */
final class WhatsappAgentAuthenticator extends AbstractAuthenticator
{
    public function __construct(
        private readonly string $agentToken,
    ) {
    }

    public function supports(Request $request): ?bool
    {
        return str_starts_with($request->getPathInfo(), '/api/whatsapp/');
    }

    public function authenticate(Request $request): Passport
    {
        $header = $request->headers->get('Authorization', '');
        if (!preg_match('/^Bearer\s+(\S+)$/i', $header, $matches)) {
            throw new AuthenticationException('Отсутствует Bearer-токен');
        }

        if (!hash_equals($this->agentToken, $matches[1])) {
            throw new AuthenticationException('Неверный токен агента');
        }

        return new SelfValidatingPassport(new UserBadge('whatsapp_agent', static fn () => new WhatsappAgentUser()));
    }

    public function onAuthenticationSuccess(Request $request, TokenInterface $token, string $firewallName): ?Response
    {
        return null;
    }

    public function onAuthenticationFailure(Request $request, AuthenticationException $exception): ?Response
    {
        return new JsonResponse(['error' => $exception->getMessageKey()], Response::HTTP_UNAUTHORIZED);
    }
}
