<?php

declare(strict_types=1);

namespace App\Repository;

use App\Entity\WhatsappOutbox;
use Doctrine\Bundle\DoctrineBundle\Repository\ServiceEntityRepository;
use Doctrine\Persistence\ManagerRegistry;

/**
 * @extends ServiceEntityRepository<WhatsappOutbox>
 */
class WhatsappOutboxRepository extends ServiceEntityRepository
{
    private const LOCK_STALE_MINUTES = 10;

    public function __construct(ManagerRegistry $registry)
    {
        parent::__construct($registry, WhatsappOutbox::class);
    }

    /**
     * @return WhatsappOutbox[]
     */
    public function claimBatch(string $agentId, int $limit): array
    {
        $conn = $this->getEntityManager()->getConnection();
        $conn->beginTransaction();

        try {
            $staleBefore = (new \DateTimeImmutable())
                ->modify(sprintf('-%d minutes', self::LOCK_STALE_MINUTES))
                ->format('Y-m-d H:i:s');

            $limit = max(1, min(20, $limit));

            $sql = <<<SQL
                SELECT id
                FROM whatsapp_outbox
                WHERE agent_id = :agentId
                  AND attempts < max_attempts
                  AND (scheduled_at IS NULL OR scheduled_at <= NOW())
                  AND (
                        status = :pending
                     OR (status = :processing AND locked_at < :staleBefore)
                  )
                ORDER BY created_at ASC
                LIMIT {$limit}
                FOR UPDATE
            SQL;

            $ids = $conn->fetchFirstColumn($sql, [
                'agentId' => $agentId,
                'pending' => WhatsappOutbox::STATUS_PENDING,
                'processing' => WhatsappOutbox::STATUS_PROCESSING,
                'staleBefore' => $staleBefore,
            ]);

            if ($ids === []) {
                $conn->commit();
                return [];
            }

            $now = (new \DateTimeImmutable())->format('Y-m-d H:i:s');
            $placeholders = implode(',', array_fill(0, count($ids), '?'));

            $conn->executeStatement(
                "UPDATE whatsapp_outbox
                 SET status = ?, locked_at = ?, locked_by = ?, attempts = attempts + 1, updated_at = ?
                 WHERE id IN ($placeholders)",
                array_merge(
                    [WhatsappOutbox::STATUS_PROCESSING, $now, $agentId, $now],
                    array_map('intval', $ids)
                )
            );

            $conn->commit();
        } catch (\Throwable $e) {
            $conn->rollBack();
            throw $e;
        }

        return $this->createQueryBuilder('o')
            ->andWhere('o.id IN (:ids)')
            ->setParameter('ids', $ids)
            ->getQuery()
            ->getResult();
    }
}
