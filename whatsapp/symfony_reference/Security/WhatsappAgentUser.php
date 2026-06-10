<?php

declare(strict_types=1);

namespace App\Security;

use Symfony\Component\Security\Core\User\UserInterface;

final class WhatsappAgentUser implements UserInterface
{
    public function getUserIdentifier(): string
    {
        return 'whatsapp_agent';
    }

    public function getRoles(): array
    {
        return ['ROLE_WHATSAPP_AGENT'];
    }

    public function eraseCredentials(): void
    {
    }
}
